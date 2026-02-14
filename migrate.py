"""
Run database migration on startup to allow NULL whatsapp.
"""
import asyncio
import logging
import asyncpg
from config import settings

logger = logging.getLogger(__name__)

async def migrate():
    """Run schema migration."""
    conn = await asyncpg.connect(settings.database_url)
    try:
        # Drop old unique constraint on whatsapp
        await conn.execute("ALTER TABLE leads_olinda DROP CONSTRAINT IF EXISTS leads_olinda_whatsapp_key;")
        logger.info("Dropped old whatsapp unique constraint")
        
        # Make whatsapp nullable
        await conn.execute("ALTER TABLE leads_olinda ALTER COLUMN whatsapp DROP NOT NULL;")
        logger.info("Made whatsapp nullable")
        
        # Add unique constraint on (business_name, category)
        await conn.execute("""
            ALTER TABLE leads_olinda 
            ADD CONSTRAINT unique_business_category 
            UNIQUE (business_name, category);
        """)
        logger.info("Added business_name+category unique constraint")
        
    except asyncpg.exceptions.DuplicateTableError:
        logger.info("Migration already applied")
    except Exception as e:
        logger.warning(f"Migration error (might be already applied): {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(migrate())
