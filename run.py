import socket
import uvicorn
from backend.config import HOST, PORT

def is_port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0

def find_available_port(host: str, start_port: int, max_attempts: int = 15) -> int:
    for p in range(start_port, start_port + max_attempts):
        if not is_port_in_use(host, p):
            return p
    return start_port

if __name__ == "__main__":
    port_to_use = PORT
    if is_port_in_use(HOST, port_to_use):
        fallback_port = find_available_port(HOST, PORT + 1)
        print(f"Notice: Port {PORT} is already occupied. Automatically using port {fallback_port} instead.")
        port_to_use = fallback_port

    print("=====================================================")
    print("LeadsEngine AI (Free Edition) Server Starting...")
    print(f"Dashboard URL: http://{HOST}:{port_to_use}")
    print("=====================================================")
    uvicorn.run("backend.server:app", host=HOST, port=port_to_use, reload=False)
