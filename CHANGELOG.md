# FILE: CHANGELOG.md
# Changelog

## [v0.3.1] — File Transfer Fixes

### Bug Fixes

#### File transfer not working (receiver side)
- Receiver was displaying raw JSON instead of processing file transfer frames.
  `_handle_privmsg` read `subtype` from the unencrypted header, but the sender
  puts it inside the encrypted body as `tag`. Fixed: receiver now checks
  `body.get("tag")` after decryption as fallback.
- Receiver got `filename=unknown, size=0` because `_handle_file_start` was
  reading fields from the outer Fernet body dict instead of the inner JSON
  string in `body["text"]`. Fixed: inner JSON is now unwrapped before dispatch.

#### File transfer silently dropped mid-transfer
- Server's privmsg rate limiter (25/15min per pair) was counting binary chunk
  frames, causing all chunks beyond the limit to be silently dropped.
  Fixed: `file_chunk_bin` frames are now exempt from the per-pair rate limiter.

#### UI freezing during file send
- `_send_file` was called directly from the input thread, blocking all input
  and output for the entire transfer duration.
  Fixed: file sends now run in a background daemon thread.

#### Progress display corruption
- Bare `print(..., end="\r")` calls bypassed the TUI lock, producing garbled
  backwards progress numbers racing with animation redraws.
  Fixed: progress uses `utils.print_msg` through the output lock.

#### Double file read on send
- SHA-256 hash for the Ed25519 signature was computed in a second full file
  read after all chunks were sent. Fixed: hash is computed inline while
  reading chunks, eliminating the redundant disk I/O.

#### Slower transfers after chunk size change
- Chunk size was incorrectly reduced to 512KB, turning a 1-frame transfer
  into 11 frames. Each frame adds bore tunnel relay latency.
  Reverted to 32MB chunks — 1 frame for files under 32MB.

#### TCP latency
- Added `TCP_NODELAY` on the client socket to disable Nagle's algorithm and
  prevent artificial send delays on the tunnel.

