#!/usr/bin/env python3
"""Minimal test to debug the Python perf implementation."""

print("Starting minimal test...")

try:
    print("Importing trio...")
    import trio
    print("✓ trio imported successfully")
    
    print("Importing multiaddr...")
    import multiaddr
    print("✓ multiaddr imported successfully")
    
    print("Importing libp2p...")
    from libp2p import new_host, create_yamux_muxer_option
    print("✓ libp2p core imported successfully")
    
    print("Importing crypto...")
    from libp2p.crypto.secp256k1 import create_new_key_pair
    from libp2p.crypto.x25519 import create_new_key_pair as create_new_x25519_key_pair
    print("✓ crypto imported successfully")
    
    print("Importing security...")
    from libp2p.security.noise.transport import PROTOCOL_ID as NOISE_PROTOCOL_ID, Transport as NoiseTransport
    print("✓ security imported successfully")
    
    print("Creating key pairs...")
    key_pair = create_new_key_pair()
    noise_key_pair = create_new_x25519_key_pair()
    print("✓ key pairs created")
    
    print("Creating NoiseTransport...")
    noise_transport = NoiseTransport(
        libp2p_keypair=key_pair,
        noise_privkey=noise_key_pair.private_key,
        early_data=None,
    )
    print("✓ NoiseTransport created")
    
    print("Creating security options...")
    security_options = {NOISE_PROTOCOL_ID: noise_transport}
    print("✓ security options created")
    
    print("Creating muxer options...")
    muxer_options = create_yamux_muxer_option()
    print("✓ muxer options created")
    
    print("Creating listen addresses...")
    listen_addrs = [multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/4001")]
    print("✓ listen addresses created")
    
    print("Creating host...")
    host = new_host(
        key_pair=key_pair,
        sec_opt=security_options,
        muxer_opt=muxer_options,
    )
    print("✓ host created successfully")
    
    print("All imports and basic setup successful!")
    
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
