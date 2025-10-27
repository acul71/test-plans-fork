#!/usr/bin/env python3
"""Debug server to isolate the port binding issue."""

import trio
import multiaddr
from libp2p import new_host, create_yamux_muxer_option
from libp2p.security.noise.transport import PROTOCOL_ID as NOISE_PROTOCOL_ID, Transport as NoiseTransport
from libp2p.crypto.secp256k1 import create_new_key_pair as create_secp256k1_key_pair
from libp2p.crypto.x25519 import create_new_key_pair as create_x25519_key_pair
import hashlib

async def debug_server():
    """Debug server to test port binding."""
    print("Creating deterministic key pair...")
    fixed_seed = hashlib.sha256(b"perf-test-fixed-seed-for-consistent-peer-id").digest()
    key_pair = create_secp256k1_key_pair(fixed_seed)
    noise_key_pair = create_x25519_key_pair()
    
    print("Creating Noise transport...")
    noise_transport = NoiseTransport(
        libp2p_keypair=key_pair,
        noise_privkey=noise_key_pair.private_key,
        early_data=None,
    )
    security_options = {NOISE_PROTOCOL_ID: noise_transport}
    
    print("Creating muxer options...")
    muxer_options = create_yamux_muxer_option()
    
    print("Creating host...")
    host = new_host(
        key_pair=key_pair,
        sec_opt=security_options,
        muxer_opt=muxer_options,
    )
    
    print(f"Host created with ID: {host.get_id()}")
    
    print("Creating listen address...")
    listen_addr = multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/4001")
    print(f"Listen address: {listen_addr}")
    
    print("Starting host...")
    try:
        async with host.run(listen_addrs=[listen_addr]):
            print("Host started successfully!")
            print(f"Host addresses: {host.get_addrs()}")
            
            # Check if port is actually bound
            import subprocess
            result = subprocess.run(['lsof', '-i', ':4001'], capture_output=True, text=True)
            print(f"Port 4001 status: {result.stdout if result.stdout else 'NOT BOUND'}")
            
            print("Server running, waiting for connections...")
            await trio.sleep_forever()
    except Exception as e:
        print(f"Error starting host: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    trio.run(debug_server)
