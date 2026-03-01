#!/bin/bash

# SpecTestPilot API Testing Script
# Clean, simple script that works with ANY OpenAPI spec

set -e

# Config
SPEC_FILE="${1:-sample_api.yaml}"
PORT="${2:-8000}"
BASE_URL="http://localhost:$PORT"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_header() {
    echo -e "\n${BLUE}$1${NC}"
    echo -e "${BLUE}$(printf '=%.0s' $(seq 1 ${#1}))${NC}\n"
}

print_success() { echo -e "${GREEN}✅ $1${NC}"; }
print_error() { echo -e "${RED}❌ $1${NC}"; }
print_info() { echo -e "${YELLOW}ℹ️  $1${NC}"; }

cleanup() {
    if [ -n "$SERVER_PID" ] && kill -0 $SERVER_PID 2>/dev/null; then
        echo "🛑 Stopping server..."
        kill $SERVER_PID 2>/dev/null || true
        wait $SERVER_PID 2>/dev/null || true
    fi
    
    # Kill anything on port
    if lsof -ti:$PORT >/dev/null 2>&1; then
        kill -9 $(lsof -ti:$PORT) 2>/dev/null || true
    fi
}

trap cleanup EXIT INT TERM

start_server() {
    print_info "Starting dynamic API server for $SPEC_FILE..."
    
    # Kill existing server
    cleanup
    
    # Start new server
    PYTHONPATH=. venv/bin/python api_server.py --spec $SPEC_FILE --port $PORT &
    SERVER_PID=$!
    
    # Wait for startup
    for i in {1..20}; do
        if curl -s $BASE_URL/health >/dev/null 2>&1; then
            print_success "Server running at $BASE_URL"
            return 0
        fi
        echo -n "."
        sleep 1
    done
    
    print_error "Server failed to start"
    return 1
}

test_api() {
    print_info "Testing API endpoints..."
    
    # Get available endpoints
    endpoints=$(curl -s $BASE_URL/openapi.json | jq -r '.paths | to_entries[] | "\(.key):\(.value | keys | join(","))"' 2>/dev/null || echo "")
    
    if [ -z "$endpoints" ]; then
        print_error "Could not fetch API endpoints"
        return 1
    fi
    
    echo -e "\n📍 Available endpoints:"
    echo "$endpoints" | while read line; do
        echo "   $line"
    done
    
    echo -e "\n🧪 Running core tests:"
    
    # Test 1: First GET endpoint
    first_get=$(echo "$endpoints" | grep -E "GET|get" | head -1 | cut -d: -f1)
    if [ -n "$first_get" ]; then
        echo -n "   GET $first_get (with auth) → "
        status=$(curl -s -w "%{http_code}" -o /dev/null -H "Authorization: Bearer test-token" $BASE_URL$first_get)
        if [ "$status" = "200" ]; then
            echo -e "${GREEN}✅ $status${NC}"
        else
            echo -e "${YELLOW}⚠️  $status${NC}"
        fi
        
        echo -n "   GET $first_get (no auth) → "
        status=$(curl -s -w "%{http_code}" -o /dev/null $BASE_URL$first_get)
        if [ "$status" = "401" ]; then
            echo -e "${GREEN}✅ $status${NC}"
        else
            echo -e "${YELLOW}⚠️  $status${NC}"
        fi
    fi
    
    # Test 2: First POST endpoint  
    first_post=$(echo "$endpoints" | grep -E "POST|post" | head -1 | cut -d: -f1)
    if [ -n "$first_post" ]; then
        echo -n "   POST $first_post (create) → "
        status=$(curl -s -w "%{http_code}" -o /dev/null -X POST -H "Authorization: Bearer test-token" -H "Content-Type: application/json" -d '{"name":"test","data":"sample"}' $BASE_URL$first_post)
        if [ "$status" = "201" ] || [ "$status" = "200" ]; then
            echo -e "${GREEN}✅ $status${NC}"
        else
            echo -e "${YELLOW}⚠️  $status${NC}"
        fi
        
        echo -n "   POST $first_post (empty body) → "
        status=$(curl -s -w "%{http_code}" -o /dev/null -X POST -H "Authorization: Bearer test-token" -H "Content-Type: application/json" -d '{}' $BASE_URL$first_post)
        if [ "$status" = "400" ]; then
            echo -e "${GREEN}✅ $status${NC}"
        else
            echo -e "${YELLOW}⚠️  $status${NC}"
        fi
    fi
}

generate_tests() {
    print_info "Generating test cases with SpecTestPilot..."
    
    # Generate test cases
    PYTHONPATH=. venv/bin/python run_agent.py --spec $SPEC_FILE --output generated_tests.json
    
    if [ ! -f "generated_tests.json" ]; then
        print_error "Failed to generate test cases"
        return 1
    fi
    
    test_count=$(jq -r '.test_suite | length' generated_tests.json 2>/dev/null || echo "0")
    print_success "Generated $test_count test cases"
    
    # Convert to executable formats
    print_info "Converting to executable formats..."
    
    mkdir -p output
    
    # Generate pytest
    PYTHONPATH=. venv/bin/python generate_tests.py \
        --input generated_tests.json \
        --format pytest \
        --base-url $BASE_URL \
        --output output/test_suite.py
    
    # Generate curl
    PYTHONPATH=. venv/bin/python generate_tests.py \
        --input generated_tests.json \
        --format curl \
        --base-url $BASE_URL \
        --output output/curl_tests.sh
    
    chmod +x output/curl_tests.sh
    
    print_success "Generated executable tests in output/"
}

main() {
    print_header "🚀 SpecTestPilot API Testing"
    
    if [ ! -f "$SPEC_FILE" ]; then
        print_error "OpenAPI spec file not found: $SPEC_FILE"
        echo "Usage: $0 [spec_file] [port]"
        echo "Example: $0 my_api.yaml 8000"
        exit 1
    fi
    
    print_info "Testing API: $SPEC_FILE"
    print_info "Server port: $PORT"
    
    # Main workflow
    start_server || exit 1
    
    test_api || print_error "API testing had issues"
    
    generate_tests || print_error "Test generation had issues"
    
    print_header "🎉 Testing Complete!"
    
    echo "📋 What's available:"
    echo "   🌐 Interactive docs: $BASE_URL/docs"
    echo "   📊 Health check: $BASE_URL/health"
    echo "   📁 Generated tests: output/"
    echo "   📝 Test cases: generated_tests.json"
    echo ""
    echo "📝 Try these commands:"
    echo "   # Run pytest"
    echo "   venv/bin/python -m pytest output/test_suite.py -v"
    echo ""
    echo "   # Run curl tests"  
    echo "   bash output/curl_tests.sh"
    echo ""
    echo "🛑 Press Ctrl+C to stop server"
    
    # Keep server running
    wait $SERVER_PID
}

# Show help
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "SpecTestPilot API Testing Script"
    echo ""
    echo "Usage: $0 [spec_file] [port]"
    echo ""  
    echo "Examples:"
    echo "  $0                           # Use sample_api.yaml on port 8000"
    echo "  $0 my_api.yaml              # Use my_api.yaml on port 8000"
    echo "  $0 banking_api.yaml 9000    # Use banking_api.yaml on port 9000"
    echo ""
    echo "This script will:"
    echo "  1. Start dynamic FastAPI mock server"
    echo "  2. Test core API functionality"
    echo "  3. Generate test cases with SpecTestPilot"
    echo "  4. Convert to executable tests (pytest/curl)"
    echo "  5. Keep server running for manual testing"
    exit 0
fi

main
