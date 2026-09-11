import os
import platform
import tempfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# Smart cross-platform database path:
# On Windows: uses data/debate_tab.db inside the project folder
# On Linux/containers: uses /tmp/debate_tab.db for maximum filesystem lock performance
if platform.system() == "Windows":
    default_db_path = os.path.join(DATA_DIR, "debate_tab.db")
else:
    default_db_path = os.path.join(tempfile.gettempdir(), "debate_tab.db")

DB_PATH = os.environ.get("DEBATE_DB_PATH", default_db_path)
BACKUP_DB_PATH = os.path.join(DATA_DIR, "debate_tab_backup.db")

# Default Admin credentials for initial setup
DEFAULT_ADMIN_NAME = "Tab Director"
DEFAULT_ADMIN_WHATSAPP = "01700000000"
DEFAULT_ADMIN_PIN = "778899"

# Session timeout in seconds (24 hours)
SESSION_EXPIRE_SECONDS = 86400

# Security secret for hashing/signing
SECRET_KEY = os.environ.get("DEBATE_SECRET_KEY", "traditional-debate-tab-master-secret-key-2026")
