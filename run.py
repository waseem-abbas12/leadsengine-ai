import uvicorn
from backend.config import HOST, PORT

if __name__ == "__main__":
    print(f"=====================================================")
    print(f"🚀 LeadsEngine AI (Free Edition) Server Starting...")
    print(f"🌐 Dashboard URL: http://{HOST}:{PORT}")
    print(f"=====================================================")
    uvicorn.run("backend.server:app", host=HOST, port=PORT, reload=False)
