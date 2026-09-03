import aiosqlite
from config import DB_PATH


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                user_name TEXT,
                content_type TEXT NOT NULL,
                text_content TEXT,
                file_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS dialogs (
                admin_msg_id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def add_post(user_id: int, user_name: str, content_type: str,
                    text_content: str | None, file_id: str | None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO posts (user_id, user_name, content_type, text_content, file_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, user_name, content_type, text_content, file_id),
        )
        await db.commit()
        return cursor.lastrowid


async def get_post(post_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM posts WHERE id = ?", (post_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_post_status(post_id: int, status: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE posts SET status = ? WHERE id = ?", (status, post_id))
        await db.commit()


async def save_dialog(admin_msg_id: int, user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO dialogs (admin_msg_id, user_id) VALUES (?, ?)",
            (admin_msg_id, user_id),
        )
        await db.commit()


async def get_dialog_user(admin_msg_id: int) -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT user_id FROM dialogs WHERE admin_msg_id = ?", (admin_msg_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None
