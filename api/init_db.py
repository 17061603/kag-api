"""
数据库初始化脚本
用于手动初始化数据库表结构
"""
import asyncio
from database.connection import init_db, close_db


async def main():
    """初始化数据库"""
    print("正在初始化数据库...")
    try:
        await init_db()
        print("数据库初始化成功！")
    except Exception as e:
        print(f"数据库初始化失败: {e}")
        raise
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())

