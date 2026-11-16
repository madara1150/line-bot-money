import os
import sys
import tempfile

# Settings must exist before app.config is imported.
_tmp = tempfile.mkdtemp(prefix="expense-bot-test-")
os.environ.update(
    LINE_CHANNEL_SECRET="test-secret",
    LINE_CHANNEL_ACCESS_TOKEN="test-token",
    ALLOWED_USER_IDS="Uowner",
    DATA_DIR=_tmp,
)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
