SELECT 'CREATE DATABASE directus'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'directus')\gexec

SELECT 'CREATE DATABASE n8n'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'n8n')\gexec
