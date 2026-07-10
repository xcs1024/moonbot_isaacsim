#!/usr/bin/env python3
from __future__ import annotations

import argparse
import signal
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
import pyrealsense2 as rs


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve a RealSense color stream as MJPEG.")
    parser.add_argument("--serial", required=True, help="RealSense serial number.")
    parser.add_argument("--name", default="realsense", help="Display name.")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP bind host.")
    parser.add_argument("--port", type=int, default=8091, help="HTTP port.")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--quality", type=int, default=85)
    args = parser.parse_args()

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_device(args.serial)
    config.enable_stream(rs.stream.color, args.width, args.height, rs.format.bgr8, args.fps)
    pipeline.start(config)
    running = True

    def stop(*_: object) -> None:
        nonlocal running
        running = False
        try:
            pipeline.stop()
        finally:
            sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *values: object) -> None:
            return

        def do_GET(self) -> None:
            if self.path in {"/", "/index.html"}:
                body = (
                    "<!doctype html><html><head><meta charset='utf-8'>"
                    f"<title>{args.name}</title>"
                    "<style>body{margin:0;background:#111;color:#eee;font-family:sans-serif;"
                    "display:grid;place-items:center;min-height:100vh}"
                    "main{width:min(96vw,960px)}img{width:100%;height:auto;background:#000}"
                    "p{opacity:.75}</style></head><body><main>"
                    f"<h2>{args.name} RealSense {args.serial}</h2>"
                    "<img src='/stream.mjpg'>"
                    "<p>Refresh if the stream pauses.</p>"
                    "</main></body></html>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path != "/stream.mjpg":
                self.send_error(404)
                return

            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            while running:
                try:
                    frames = pipeline.wait_for_frames(1000)
                    color = frames.get_color_frame()
                    if not color:
                        continue
                    image = np.asanyarray(color.get_data())
                    ok, jpg = cv2.imencode(
                        ".jpg",
                        image,
                        [int(cv2.IMWRITE_JPEG_QUALITY), args.quality],
                    )
                    if not ok:
                        continue
                    data = jpg.tobytes()
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(data)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break
                except Exception as exc:
                    print(f"stream error: {exc}", flush=True)
                    time.sleep(0.1)

    print(
        f"{args.name} RealSense MJPEG server on http://{args.host}:{args.port}",
        flush=True,
    )
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
