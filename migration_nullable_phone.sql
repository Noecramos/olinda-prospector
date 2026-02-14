-- Migration: Allow NULL whatsapp and add business_name uniqueness
-- Run this on existing Railway databases BEFORE deploying the new code

-- Step 1: Drop the old UNIQUE constraint on whatsapp
ALTER TABLE leads_olinda DROP CONSTRAINT IF EXISTS leads_olinda_whatsapp_key;

-- Step 2: Make whatsapp nullable
ALTER TABLE leads_olinda ALTER COLUMN whatsapp DROP NOT NULL;

-- Step 3: Add unique constraint on (business_name, category)
ALTER TABLE leads_olinda ADD CONSTRAINT unique_business_category UNIQUE (business_name, category);
