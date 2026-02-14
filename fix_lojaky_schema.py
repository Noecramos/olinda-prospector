"""
One-time script to fix Lojaky database schema.
Run this locally to manually apply the migration.
"""
import asyncio
import asyncpg

# Lojaky database URL from Railway
# Go to Railway -> Postgres-Bucl -> Variables -> copy DATABASE_URL
LOJAKY_DATABASE_URL = input("Paste Lojaky DATABASE_URL from Railway: ").strip()

async def fix_schema():
    print("Connecting to Lojaky database...")
    conn = await asyncpg.connect(LOJAKY_DATABASE_URL)
    
    try:
        # Step 1: Drop old whatsapp unique constraint
        print("1. Dropping old whatsapp constraint...")
        await conn.execute("ALTER TABLE leads_olinda DROP CONSTRAINT IF EXISTS leads_olinda_whatsapp_key;")
        print("   ✓ Done")
        
        # Step 2: Make whatsapp nullable
        print("2. Making whatsapp nullable...")
        await conn.execute("ALTER TABLE leads_olinda ALTER COLUMN whatsapp DROP NOT NULL;")
        print("   ✓ Done")
        
        # Step 3: Check if constraint already exists
        print("3. Checking for existing unique constraint...")
        result = await conn.fetchval("""
            SELECT COUNT(*) FROM pg_constraint 
            WHERE conname = 'unique_business_category'
        """)
        
        if result > 0:
            print("   ⚠ Constraint already exists, dropping it first...")
            await conn.execute("ALTER TABLE leads_olinda DROP CONSTRAINT unique_business_category;")
        
        # Step 4: Add new unique constraint
        print("4. Adding business_name + category unique constraint...")
        await conn.execute("""
            ALTER TABLE leads_olinda 
            ADD CONSTRAINT unique_business_category 
            UNIQUE (business_name, category)
        """)
        print("   ✓ Done")
        
        print("\n✅ Schema migration completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(fix_schema())
