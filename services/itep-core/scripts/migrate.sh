#!/usr/bin/env sh
set -eu

echo "Validating Prisma schema..."
npx prisma validate

echo "Generating Prisma client..."
npx prisma generate

echo "Applying migrations..."
npx prisma migrate deploy

echo "Migration completed."
