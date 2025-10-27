#!/usr/bin/env python3
"""
Python libp2p perf implementation for performance benchmarking.

This implementation follows the libp2p perf protocol specification:
- Implements the /perf/1.0.0 protocol for bidirectional data transfer
- Supports both server and client modes
- Measures throughput and latency
- Outputs JSON progress reports and final results
"""

import argparse
import json
import logging
import struct
import sys
import time
from typing import Optional, Tuple

import trio
import multiaddr
from libp2p import new_host, create_yamux_muxer_option, create_mplex_muxer_option
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream
from libp2p.utils.address_validation import (
    get_available_interfaces,
    get_optimal_binding_address,
)
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.security.noise.transport import PROTOCOL_ID as NOISE_PROTOCOL_ID, Transport as NoiseTransport
from libp2p.security.insecure.transport import PLAINTEXT_PROTOCOL_ID, InsecureTransport
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.crypto.x25519 import create_new_key_pair as create_x25519_key_pair

# Protocol constants
PERF_PROTOCOL_ID = TProtocol("/perf/1.0.0")
BLOCK_SIZE = 64 * 1024  # 64KB blocks
REPORT_INTERVAL = 1.0  # Report every second

# Get logger for this module
logger = logging.getLogger("libp2p.perf")

def configure_logging():
    """Configure logging for perf tests."""
    # Set root logger to INFO level to see important messages
    logging.getLogger().setLevel(logging.INFO)
    
    # Keep our own logging at INFO level for important messages
    logging.getLogger("libp2p.perf").setLevel(logging.INFO)
    
    # Suppress noisy modules
    logging.getLogger("multiaddr").setLevel(logging.WARNING)
    logging.getLogger("libp2p").setLevel(logging.WARNING)
    logging.getLogger("libp2p.transport").setLevel(logging.WARNING)


class PerfService:
    """Implements the libp2p perf protocol."""
    
    def __init__(self, host):
        self.host = host
        self.host.set_stream_handler(PERF_PROTOCOL_ID, self.handle_perf_request)
    
    async def handle_perf_request(self, stream: INetStream) -> None:
        """Handle incoming perf requests (server side)."""
        try:
            # Read 8-byte header indicating how many bytes to send back
            header = await stream.read(8)
            if len(header) != 8:
                logger.error("Invalid header length")
                await stream.reset()
                return
            
            bytes_to_send = struct.unpack('>Q', header)[0]  # Big-endian uint64
            logger.debug(f"Server: need to send {bytes_to_send} bytes back")
            
            # Drain the incoming stream (client's upload data)
            await self.drain_stream(stream)
            
            # Send the requested bytes back to client
            if bytes_to_send > 0:
                await self.send_bytes(stream, bytes_to_send)
            
            # Close write side
            await stream.close()
            
        except Exception as e:
            logger.error(f"Error in perf handler: {e}")
            await stream.reset()
    
    async def run_perf_client(self, peer_id, upload_bytes: int, download_bytes: int) -> None:
        """Run perf test as client."""
        try:
            # Open stream to server
            stream = await self.host.new_stream(peer_id, [PERF_PROTOCOL_ID])
            
            # Send 8-byte header indicating how many bytes server should send back
            header = struct.pack('>Q', download_bytes)  # Big-endian uint64
            await stream.write(header)
            
            # Send upload data if specified
            if upload_bytes > 0:
                await self.send_bytes_with_progress(stream, upload_bytes)
            
            # Close write side
            await stream.close()
            
            # Receive download data if specified
            if download_bytes > 0:
                await self.receive_bytes_with_progress(stream, download_bytes)
            
        except Exception as e:
            logger.error(f"Error in perf client: {e}")
            raise
    
    async def send_bytes(self, stream: INetStream, bytes_to_send: int) -> None:
        """Send bytes to stream without progress reporting."""
        buffer = bytearray(BLOCK_SIZE)
        bytes_sent = 0
        
        while bytes_sent < bytes_to_send:
            chunk_size = min(BLOCK_SIZE, bytes_to_send - bytes_sent)
            chunk = buffer[:chunk_size]
            await stream.write(chunk)
            bytes_sent += chunk_size
    
    async def send_bytes_with_progress(self, stream: INetStream, bytes_to_send: int) -> None:
        """Send bytes to stream with progress reporting."""
        buffer = bytearray(BLOCK_SIZE)
        bytes_sent = 0
        last_report_time = time.time()
        last_report_bytes = 0
        
        while bytes_sent < bytes_to_send:
            chunk_size = min(BLOCK_SIZE, bytes_to_send - bytes_sent)
            chunk = buffer[:chunk_size]
            await stream.write(chunk)
            bytes_sent += chunk_size
            
            # Report progress every second
            now = time.time()
            if now - last_report_time >= REPORT_INTERVAL:
                elapsed = now - last_report_time
                report_bytes = bytes_sent - last_report_bytes
                
                result = {
                    "type": "intermediary",
                    "timeSeconds": elapsed,
                    "uploadBytes": report_bytes,
                    "downloadBytes": 0
                }
                print(json.dumps(result))
                
                last_report_time = now
                last_report_bytes = bytes_sent
    
    async def receive_bytes_with_progress(self, stream: INetStream, expected_bytes: int) -> None:
        """Receive bytes from stream with progress reporting."""
        bytes_received = 0
        last_report_time = time.time()
        last_report_bytes = 0
        
        while bytes_received < expected_bytes:
            chunk = await stream.read(BLOCK_SIZE)
            if not chunk:
                break
            
            bytes_received += len(chunk)
            
            # Report progress every second
            now = time.time()
            if now - last_report_time >= REPORT_INTERVAL:
                elapsed = now - last_report_time
                report_bytes = bytes_received - last_report_bytes
                
                result = {
                    "type": "intermediary",
                    "timeSeconds": elapsed,
                    "uploadBytes": 0,
                    "downloadBytes": report_bytes
                }
                print(json.dumps(result))
                
                last_report_time = now
                last_report_bytes = bytes_received
        
        if bytes_received != expected_bytes:
            logger.warning(f"Expected {expected_bytes} bytes, received {bytes_received}")
    
    async def drain_stream(self, stream: INetStream) -> int:
        """Drain all data from stream."""
        bytes_drained = 0
        while True:
            chunk = await stream.read(BLOCK_SIZE)
            if not chunk:
                break
            bytes_drained += len(chunk)
        return bytes_drained


class PerfTest:
    """Main perf test implementation."""
    
    def __init__(self):
        logger.info("Initializing PerfTest...")
        self.host = None
        self.perf_service = None
        logger.info("PerfTest initialized successfully")
    
    def create_security_options(self):
        """Create security options for the host."""
        # Use Noise security by default
        # Use deterministic key pairs for consistent peer IDs
        # This ensures the same peer ID every time the server starts
        import secrets
        
        # Use a deterministic seed for consistent peer IDs
        # This ensures the same peer ID every time the server starts
        import hashlib
        fixed_seed = hashlib.sha256(b"perf-test-fixed-seed-for-consistent-peer-id").digest()
        key_pair = create_new_key_pair(fixed_seed)
        noise_key_pair = create_x25519_key_pair()
        noise_transport = NoiseTransport(
            libp2p_keypair=key_pair,
            noise_privkey=noise_key_pair.private_key,
            early_data=None,
        )
        security_options = {NOISE_PROTOCOL_ID: noise_transport}
        return security_options, key_pair
    
    def create_muxer_options(self):
        """Create muxer options for the host."""
        # Use Yamux by default for better performance
        return create_yamux_muxer_option()
    
    def create_listen_address(self, ip: str, port: int = 4001) -> multiaddr.Multiaddr:
        """Create listen address."""
        return multiaddr.Multiaddr(f"/ip4/{ip}/tcp/{port}")
    
    async def run_server(self, ip: str = "0.0.0.0", port: int = 4001) -> None:
        """Run perf server."""
        logger.info("Starting perf server")
        
        # Create security and muxer options
        logger.info("Creating security options...")
        security_options, key_pair = self.create_security_options()
        logger.info("Creating muxer options...")
        muxer_options = self.create_muxer_options()
        
        # Get available interfaces for listening
        logger.info(f"Getting available interfaces for port {port}...")
        listen_addrs = get_available_interfaces(port)
        logger.info(f"Using listen addresses: {listen_addrs}")
        
        # Create host
        logger.info("Creating host...")
        self.host = new_host(
            key_pair=key_pair,
            sec_opt=security_options,
            muxer_opt=muxer_options,
            listen_addrs=listen_addrs  # Pass listen addresses to new_host
        )
        logger.info("Host created successfully")
        
        # Create perf service
        logger.info("Creating PerfService...")
        self.perf_service = PerfService(self.host)
        logger.info("PerfService created successfully")
        
        # Start the host using network service run method
        logger.info("Starting host with listen addresses...")
        try:
            logger.info("About to start network service...")
            
            # Get the network service
            network = self.host.get_network()
            
            # Start the network service using its run method
            async with trio.open_nursery() as nursery:
                # Start the network service
                nursery.start_soon(network.run)
                
                # Wait a bit for the network to start
                await trio.sleep(0.1)
                
                # Start listening on addresses
                logger.info("Starting to listen on addresses...")
                await network.listen(*listen_addrs)
                logger.info("✓ Network listening started!")
                
                # Start the peer-store cleanup task
                nursery.start_soon(self.host.get_peerstore().start_cleanup_task, 60)
                
                # Print listening addresses
                all_addrs = self.host.get_addrs()
                logger.info(f"Server listening on {len(all_addrs)} addresses:")
                for addr in all_addrs:
                    # Add peer ID to create full multiaddr
                    full_addr = f"{addr}/p2p/{self.host.get_id()}"
                    logger.info(f"  {full_addr}")
                
                logger.info("Server running, waiting for connections...")
                
                # Run forever until interrupted
                try:
                    await trio.sleep_forever()
                except KeyboardInterrupt:
                    logger.info("Server interrupted")
        except Exception as e:
            logger.error(f"Error starting server: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    async def run_client(self, server_address: str, transport: str, 
                        upload_bytes: int, download_bytes: int) -> None:
        """Run perf client."""
        logger.info(f"Starting perf client to {server_address}")
        
        # Parse server address
        host, port = self.parse_server_address(server_address)
        
        # Create multiaddr based on transport
        if transport == "tcp":
            multiaddr_str = f"/ip4/{host}/tcp/{port}"
        elif transport == "quic-v1":
            multiaddr_str = f"/ip4/{host}/udp/{port}/quic-v1"
        else:
            raise ValueError(f"Unsupported transport: {transport}")
        
        # For testing, we'll connect without peer ID first
        # In a real implementation, this would be exchanged via discovery
        # The server will use a deterministic peer ID, so we can connect without specifying it
        
        # Parse multiaddr and create peer info
        maddr = multiaddr.Multiaddr(multiaddr_str)
        # The server uses a deterministic peer ID that we know
        # This matches the Go implementation approach
        from libp2p.peer.peerinfo import PeerInfo
        from libp2p.peer.id import ID
        # Use the known deterministic server peer ID
        # This is generated by the same deterministic seed as the server
        server_peer_id = ID.from_base58("16Uiu2HAmTRtKf1bk71cFL4WChE4XGjS33xJTJ1gDYXRwjmsLu7EE")
        info = PeerInfo(server_peer_id, [maddr])
        
        # Create security and muxer options for CLIENT
        # Client should use its own key pair, not the server's
        client_key_pair = create_new_key_pair()  # Random key for client
        client_noise_key_pair = create_x25519_key_pair()
        client_noise_transport = NoiseTransport(
            libp2p_keypair=client_key_pair,
            noise_privkey=client_noise_key_pair.private_key,
            early_data=None,
        )
        security_options = {NOISE_PROTOCOL_ID: client_noise_transport}
        muxer_options = self.create_muxer_options()
        
        # Create host
        self.host = new_host(
            key_pair=client_key_pair,
            sec_opt=security_options,
            muxer_opt=muxer_options
        )
        
        # Create perf service
        self.perf_service = PerfService(self.host)
        
        # Start the host and run perf test using nursery pattern
        async with self.host.run(listen_addrs=[]), trio.open_nursery() as nursery:
            # Start the peer-store cleanup task (like in examples)
            nursery.start_soon(self.host.get_peerstore().start_cleanup_task, 60)
            
            # Connect to server
            logger.info(f"Connecting to {multiaddr_str}")
            try:
                await self.host.connect(info)
                logger.info("Connected successfully")
            except Exception as e:
                logger.error(f"Failed to connect: {e}")
                import traceback
                traceback.print_exc()
                raise
            
            # Record start time
            start_time = time.time()
            
            # Run perf test
            await self.perf_service.run_perf_client(
                info.peer_id, upload_bytes, download_bytes
            )
            
            # Calculate total time
            total_time = time.time() - start_time
            
            # Output final result
            result = {
                "type": "final",
                "timeSeconds": total_time,
                "uploadBytes": upload_bytes,
                "downloadBytes": download_bytes
            }
            print(json.dumps(result))
    
    def parse_server_address(self, server_address: str) -> Tuple[str, int]:
        """Parse server address into host and port."""
        if ":" in server_address:
            host, port = server_address.split(":")
            return host, int(port)
        else:
            return server_address, 4001


async def main():
    """Main entry point."""
    logger.info("Starting perf.py main function...")
    configure_logging()
    
    logger.info("Parsing arguments...")
    parser = argparse.ArgumentParser(description="Python libp2p perf implementation")
    parser.add_argument("--run-server", action="store_true", 
                       help="Run as server")
    parser.add_argument("--server-address", type=str, default="",
                       help="Server address (host:port)")
    parser.add_argument("--transport", type=str, default="tcp",
                       choices=["tcp", "quic-v1"],
                       help="Transport to use")
    parser.add_argument("--upload-bytes", type=int, default=0,
                       help="Upload bytes")
    parser.add_argument("--download-bytes", type=int, default=0,
                       help="Download bytes")
    
    args = parser.parse_args()
    logger.info(f"Parsed arguments: {args}")
    
    logger.info("Creating PerfTest instance...")
    perf_test = PerfTest()
    logger.info("PerfTest instance created")
    
    try:
        if args.run_server:
            # Parse server address for binding
            if args.server_address:
                host, port = perf_test.parse_server_address(args.server_address)
            else:
                host, port = "0.0.0.0", 4001
            
            await perf_test.run_server(host, port)
        else:
            if not args.server_address:
                logger.error("Server address required for client mode")
                sys.exit(1)
            
            await perf_test.run_client(
                args.server_address,
                args.transport,
                args.upload_bytes,
                args.download_bytes
            )
    
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    trio.run(main)
