"""A stand-in for a Chromium browser's DevTools pipe (Windows): it reads commands from the handle passed
in --remote-debugging-io-pipes, answers Storage.getCookies after an unrelated event, and ends on
Browser.close."""

import json
import msvcrt
import os
import sys

switch = next(arg for arg in sys.argv if arg.startswith("--remote-debugging-io-pipes="))
read_handle, write_handle = (int(value) for value in switch.split("=", 1)[1].split(","))
commands = msvcrt.open_osfhandle(read_handle, os.O_RDONLY)
answers = msvcrt.open_osfhandle(write_handle, 0)


def say(message: dict) -> None:
    os.write(answers, json.dumps(message).encode("utf-8") + b"\0")


buffer = b""
while True:
    chunk = os.read(commands, 65536)
    if not chunk:
        sys.exit(1)
    buffer += chunk
    while b"\0" in buffer:
        raw, buffer = buffer.split(b"\0", 1)
        command = json.loads(raw)
        if command["method"] == "Browser.close":
            sys.exit(0)
        say({"method": "Target.targetCreated", "params": {}})
        result = {"cookies": [{"name": "SID", "value": "x", "domain": ".example.com"}]} \
            if command["method"] == "Storage.getCookies" else {}
        say({"id": command["id"], "result": result})
