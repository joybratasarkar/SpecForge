#!/bin/bash
# Setup Git and push to GitHub

cd "$(dirname "$0")"

echo "Setting up Git repository..."

# Configure Git user
git config user.email "joybrata007@gmail.com"
git config user.name "Joybrata Sarkar"

# Initialize repository
git init

# Add all files except sensitive ones
git add .

# Create initial commit
git commit -m "Initial commit: SpecTestPilot - RL-trainable OpenAPI test generator"

# Rename branch to main
git branch -M main

# Add remote origin
git remote add origin https://github.com/joybratasarkar/spec-test-pilot-.git

# Push to GitHub
echo ""
echo "Pushing to GitHub..."
git push -u origin main

echo ""
echo "✅ Repository setup complete!"
echo "🔗 https://github.com/joybratasarkar/spec-test-pilot-"
