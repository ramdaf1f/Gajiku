import os
# 🔥 UBAH BARIS INI: Beri tahu Python untuk mengambil dari folder 'app', bukan file 'app.py'
from app.__init__ import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    debug_env = os.environ.get("FLASK_DEBUG", "").strip().lower()
    debug = debug_env in ("1", "true", "yes", "on")
    app.run(
        host="0.0.0.0",
        port=port,
        debug=debug,
        threaded=False,
        use_reloader=debug,
    )
