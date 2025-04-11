from flask import Flask, request, jsonify, render_template, Response, stream_with_context
import requests
import traceback
import json
import time
import random
import re
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys

import gc

MAX_WORKERS = 3  # Reduced from 5 to reduce memory usage
BATCH_SIZE = 10  # Reduced from 20 to process smaller batches
REQUEST_TIMEOUT = 15  # Timeout for individual API requests in seconds
GC_ENABLED = True  # Enable garbage collection between batches

app = Flask(__name__, static_folder="static", template_folder="templates")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Configure the maximum number of concurrent API requests
MAX_WORKERS = 5
# Configure batch size for large requests
BATCH_SIZE = 20

@app.route('/')
def index():
    """Serve the main HTML page"""
    return render_template('index.html')

sys.setrecursionlimit(2000)  # Default is usually 1000

def get_region_info(session_id):
    """Get region ID and details from Voila API using session ID"""
    try:
        url = "https://voila.ca/api/cart/v1/carts/active"
        
        headers = {
            "accept": "application/json; charset=utf-8",
            "client-route-id": "d55f7f13-4217-4320-907e-eadd09051a7c",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        cookies = {
            "global_sid": session_id
        }
        
        # Add timeout to request
        response = requests.get(url, headers=headers, cookies=cookies, timeout=15)
        
        if response.status_code == 200:
            try:
                # First try parsing as JSON
                data = response.json()
                region_info = {
                    "regionId": data.get("regionId"),
                    "nickname": None,
                    "displayAddress": None,
                    "postalCode": None
                }
                
                # Extract additional information if available
                if "defaultCheckoutGroup" in data and "delivery" in data["defaultCheckoutGroup"]:
                    delivery = data["defaultCheckoutGroup"]["delivery"]
                    if "addressDetails" in delivery:
                        address = delivery["addressDetails"]
                        region_info["nickname"] = address.get("nickname")
                        region_info["displayAddress"] = address.get("displayAddress")
                        region_info["postalCode"] = address.get("postalCode")
                        
                # If we got regionId, return the information
                if region_info["regionId"]:
                    # Set a default nickname if none was found
                    if not region_info["nickname"] and region_info["regionId"]:
                        region_info["nickname"] = f"Region {region_info['regionId']}"
                    return region_info
                
                # If we couldn't get region info via JSON parsing, fall back to regex approach
                return fallback_region_extraction(response.text)
                
            except ValueError:
                # JSON parsing failed, use regex fallback
                return fallback_region_extraction(response.text)
        
        # Return a default object if there was an error
        return {
            "regionId": "unknown",
            "nickname": "Unknown Region",
            "displayAddress": "No address available",
            "postalCode": "Unknown"
        }
    
    except requests.exceptions.Timeout:
        print("Request to Voila API timed out")
        return {
            "regionId": "unknown",
            "nickname": "Timeout Error",
            "displayAddress": "API request timed out",
            "postalCode": "Unknown"
        }
    except RecursionError:
        print("Recursion error in get_region_info")
        return {
            "regionId": "unknown",
            "nickname": "Processing Error",
            "displayAddress": "Data too complex to process",
            "postalCode": "Unknown"
        }
    except Exception as e:
        print(f"Error getting region info: {str(e)}")
        return {
            "regionId": "unknown",
            "nickname": "Error",
            "displayAddress": str(e)[:50],  # Limit length to avoid issues
            "postalCode": "Unknown"
        }

def fallback_region_extraction(text_response):
    """Extract region info using regex as a fallback method"""
    # Initialize the region info with default values
    region_info = {
        "regionId": None,
        "nickname": None,
        "displayAddress": None,
        "postalCode": None
    }
    
    # Extract region ID
    region_id_match = re.search(r'"regionId"\s*:\s*"?(\d+)"?', text_response)
    if region_id_match:
        region_info["regionId"] = region_id_match.group(1)
        
    # Extract nickname
    nickname_match = re.search(r'"nickname"\s*:\s*"([^"]+)"', text_response)
    if nickname_match:
        region_info["nickname"] = nickname_match.group(1)
        
    # Extract display address
    addr_match = re.search(r'"displayAddress"\s*:\s*"([^"]+)"', text_response)
    if addr_match:
        region_info["displayAddress"] = addr_match.group(1)
        
    # Extract postal code
    postal_match = re.search(r'"postalCode"\s*:\s*"([^"]+)"', text_response)
    if postal_match:
        region_info["postalCode"] = postal_match.group(1)
        
    # If we couldn't find the region ID directly, try an alternative approach
    if not region_info["regionId"]:
        alt_region_match = re.search(r'"region"\s*:\s*{\s*"id"\s*:\s*"?(\d+)"?', text_response)
        if alt_region_match:
            region_info["regionId"] = alt_region_match.group(1)
    
    # Set a default nickname if none was found
    if not region_info["nickname"] and region_info["regionId"]:
        region_info["nickname"] = f"Region {region_info['regionId']}"
        
    return region_info
        
def parse_search_terms(search_input):
    """
    Parse search input into individual search terms.
    Handles comma-separated, newline-separated, and space-separated inputs.
    Also handles EA-code pattern recognition.
    Returns tuple of (unique_terms, duplicate_count, contains_ea_codes)
    """
    # Initialize variables to track duplicates and EA codes
    contains_ea_codes = False
    
    # First check for continuous EA codes and separate them
    if 'EA' in search_input:
        # This regex matches patterns of digits followed by 'EA'
        continuous_ea_pattern = r'(\d+EA)'
        # Replace with the same but with a space after
        search_input = re.sub(continuous_ea_pattern, r'\1 ', search_input)
        contains_ea_codes = True

    # Now try comma or newline separation
    terms = []
    if ',' in search_input or '\n' in search_input:
        # Split by commas and newlines
        terms = re.split(r'[,\n]', search_input)
    else:
        # Check for EA product codes pattern
        ea_codes = re.findall(r'\b\d+EA\b', search_input)
        if ea_codes:
            # If we found EA codes, use them
            terms = ea_codes
            contains_ea_codes = True
        else:
            # Otherwise, try splitting by spaces if the input is particularly long
            if len(search_input) > 50 and ' ' in search_input:
                terms = search_input.split()
            else:
                # Use the entire input as a single term
                terms = [search_input]
    
    # Clean up terms
    terms = [term.strip() for term in terms if term.strip()]
    
    # Count total terms before deduplication
    total_terms = len(terms)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_terms = []
    duplicates = []
    
    for term in terms:
        if term not in seen:
            seen.add(term)
            unique_terms.append(term)
        else:
            duplicates.append(term)
    
    # Calculate how many duplicates were removed
    duplicate_count = total_terms - len(unique_terms)
    
    return unique_terms, duplicate_count, contains_ea_codes, duplicates
    
def fetch_product_data(product_id, session_id):
    """Fetch product data from Voila.ca API using the provided session ID"""
    try:
        url = "https://voila.ca/api/v6/products/search"

        headers = {
            "accept": "application/json; charset=utf-8",
            "client-route-id": "5fa0016c-9764-4e09-9738-12c33fb47fc2",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        cookies = {
            "global_sid": session_id
        }

        params = {
            "term": product_id
        }

        # Add timeout to prevent hanging requests
        response = requests.get(url, headers=headers, params=params, cookies=cookies, timeout=REQUEST_TIMEOUT)

        if response.status_code != 200:
            print(f"API returned status code {response.status_code} for term {product_id}")
            return None
        
        # Use text response to avoid full JSON parsing
        text_response = response.text
        
        # Quick check for products
        if '"productId"' not in text_response and '"retailerProductId"' not in text_response:
            print(f"No products found for term {product_id}")
            return {"entities": {"product": {}}}
        
        # Create basic result structure
        result = {
            "entities": {
                "product": {}
            }
        }
        
        # Extract product IDs
        product_ids = []
        product_id_matches = re.finditer(r'"productId"\s*:\s*"([^"]+)"', text_response)
        for match in product_id_matches:
            product_ids.append(match.group(1))
        
        # Look for retailer product IDs if no direct product IDs
        if not product_ids:
            retailer_id_matches = re.finditer(r'"retailerProductId"\s*:\s*"([^"]+)"', text_response)
            for match in retailer_id_matches:
                product_ids.append("retailer_" + match.group(1))
        
        # Process each product ID
        for prod_id in product_ids:
            # Find where this product ID is mentioned
            search_pattern = f'"productId"\\s*:\\s*"{prod_id}"' if not prod_id.startswith("retailer_") else f'"retailerProductId"\\s*:\\s*"{prod_id[9:]}"'
            id_match = re.search(search_pattern, text_response)
            
            if id_match:
                # Find the containing object
                obj_start = text_response.rfind("{", 0, id_match.start())
                if obj_start >= 0:
                    # Find closing brace by counting nesting
                    brace_count = 1
                    obj_end = obj_start + 1
                    
                    while brace_count > 0 and obj_end < len(text_response):
                        if text_response[obj_end] == "{":
                            brace_count += 1
                        elif text_response[obj_end] == "}":
                            brace_count -= 1
                        obj_end += 1
                    
                    if brace_count == 0:
                        # Extract the product JSON
                        product_json = text_response[obj_start:obj_end]
                        
                        try:
                            # Parse just this product object
                            import json
                            product_data = json.loads(product_json)
                            
                            # Add to our result
                            actual_id = prod_id if not prod_id.startswith("retailer_") else product_data.get("productId", prod_id)
                            result["entities"]["product"][actual_id] = product_data
                        except json.JSONDecodeError as e:
                            print(f"Error parsing product JSON for {prod_id}: {str(e)}")
                            # Try fallback extraction
                            fallback_product = extract_product_fields(product_json, prod_id)
                            if fallback_product:
                                result["entities"]["product"][prod_id] = fallback_product
        
        # Create minimal entries if parsing failed
        if not result["entities"]["product"] and product_ids:
            print(f"Warning: Found {len(product_ids)} product IDs but couldn't parse them properly")
            for prod_id in product_ids:
                clean_id = prod_id[9:] if prod_id.startswith("retailer_") else prod_id
                result["entities"]["product"][clean_id] = {
                    "productId": clean_id,
                    "retailerProductId": product_id,
                    "name": f"Product {clean_id}",
                    "available": True
                }
        
        return result
        
    except requests.exceptions.Timeout:
        print(f"Request timeout for term {product_id}")
        return None
    except RecursionError:
        print(f"Recursion error fetching product data for {product_id}")
        return {"entities": {"product": {}}}
    except Exception as e:
        print(f"Unexpected error fetching product data for {product_id}: {str(e)}")
        return None


def extract_product_fields(product_json, product_id):
    """Extract essential product fields using regex when JSON parsing fails"""
    try:
        # Clean the product ID if it's a retailer ID
        clean_id = product_id[9:] if product_id.startswith("retailer_") else product_id
        
        # Create a basic product
        product = {
            "productId": clean_id,
            "retailerProductId": None,
            "name": None,
            "available": True,
            "brand": None,
            "categoryPath": [],
            "price": {
                "current": {
                    "amount": None,
                    "currency": "CAD"
                }
            }
        }
        
        # Extract retailerProductId - be careful with quotes and special characters
        retailer_id_match = re.search(r'"retailerProductId"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', product_json)
        if retailer_id_match:
            product["retailerProductId"] = retailer_id_match.group(1).replace('\\"', '"')
        
        # Extract name with better handling of escaped quotes and special characters
        name_match = re.search(r'"name"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', product_json)
        if name_match:
            product["name"] = name_match.group(1).replace('\\"', '"').replace('\\\\', '\\')
        
        # Extract brand with improved pattern
        brand_match = re.search(r'"brand"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', product_json)
        if brand_match:
            product["brand"] = brand_match.group(1).replace('\\"', '"').replace('\\\\', '\\')
        
        # Extract availability with more precise pattern
        available_match = re.search(r'"available"\s*:\s*(true|false)', product_json)
        if available_match:
            product["available"] = available_match.group(1) == "true"
        
        # Extract price with enhanced pattern
        price_match = re.search(r'"current"\s*:\s*{\s*"amount"\s*:\s*"([^"]+)"', product_json)
        if price_match:
            product["price"]["current"]["amount"] = price_match.group(1)
        
        # Extract image URL with better pattern
        image_match = re.search(r'"src"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', product_json)
        if image_match:
            product["image"] = {"src": image_match.group(1).replace('\\"', '"').replace('\\\\', '\\')}
        
        return product
    except Exception as e:
        print(f"Error in fallback extraction: {str(e)}")
        return None


def extract_product_info(product, search_term=None):
    """Extract product info in a memory-efficient way"""
    # Extract basic product details
    product_info = {
        "found": True,
        "searchTerm": search_term,
        "productId": product.get("productId"),
        "retailerProductId": product.get("retailerProductId"),
        "name": product.get("name"),
        "brand": product.get("brand"),
        "available": product.get("available", False),
        "imageUrl": None,
        "currency": "CAD"
    }
    
    # Safely extract image URL
    if "image" in product and isinstance(product["image"], dict):
        product_info["imageUrl"] = product["image"].get("src")
    
    # Safely extract category
    if "categoryPath" in product and isinstance(product["categoryPath"], list):
        product_info["category"] = " > ".join(product["categoryPath"])
    else:
        product_info["category"] = ""
    
    # Handle price information
    if "price" in product and isinstance(product["price"], dict):
        price_info = product["price"]
        
        # Current price
        if "current" in price_info and isinstance(price_info["current"], dict):
            product_info["currentPrice"] = price_info["current"].get("amount")
            product_info["currency"] = price_info["current"].get("currency", "CAD")
            
        # Original price
        if "original" in price_info and isinstance(price_info["original"], dict):
            product_info["originalPrice"] = price_info["original"].get("amount")
            
            # Calculate discount percentage
            if ("currentPrice" in product_info and "originalPrice" in product_info and
                product_info["currentPrice"] is not None and product_info["originalPrice"] is not None):
                try:
                    current_price = float(product_info["currentPrice"])
                    original_price = float(product_info["originalPrice"])
                    
                    if original_price > current_price:
                        discount = ((original_price - current_price) / original_price * 100)
                        product_info["discountPercentage"] = round(discount)
                except (ValueError, TypeError):
                    pass
                    
        # Unit price
        if "unit" in price_info and isinstance(price_info["unit"], dict):
            if "current" in price_info["unit"] and isinstance(price_info["unit"]["current"], dict):
                product_info["unitPrice"] = price_info["unit"]["current"].get("amount")
            product_info["unitLabel"] = price_info["unit"].get("label")
    
    # Extract offers, limiting to 5 to save memory
    if "offers" in product and isinstance(product["offers"], list):
        offers = product.get("offers", [])
        product_info["offers"] = offers[:5] if offers else []
        
    if "offer" in product:
        product_info["primaryOffer"] = product.get("offer")
    
    return product_info

def process_term(term, session_id, limit, is_article_search=True):
    """Process a single search term and return products found"""
    try:
        # Fetch data from Voila API
        raw_data = fetch_product_data(term, session_id)
        
        if not raw_data:
            # Return a not-found entry if we couldn't get data for this term
            return {
                "found": False,
                "searchTerm": term,
                "productId": None,
                "retailerProductId": None,
                "name": f"Article Not Found: {term}",
                "brand": None,
                "available": False,
                "category": "",
                "imageUrl": None,
                "notFoundMessage": f"The article \"{term}\" was not found. It may not be published yet or could be a typo."
            }, 0
        
        # Check for product entities
        if "entities" in raw_data and "product" in raw_data["entities"]:
            product_entities = raw_data["entities"]["product"]
            
            if product_entities:
                total_found = len(product_entities)
                
                # Different handling for article search vs. generic search
                if is_article_search:
                    # For article search, we typically want the first/best match
                    product_keys = list(product_entities.keys())[:1]
                else:
                    # For generic search, apply the user-specified limit
                    if limit != 'all':
                        try:
                            max_items = int(limit) if isinstance(limit, str) else limit
                            product_keys = list(product_entities.keys())[:max_items]
                        except (ValueError, TypeError):
                            product_keys = list(product_entities.keys())[:10]  # Default to 10
                    else:
                        # For 'all', return all products up to a maximum (50)
                        product_keys = list(product_entities.keys())[:50]
                
                # Process products and return them all for generic search
                if not is_article_search and len(product_keys) > 0:
                    # For generic search, return a list of all products
                    all_products = []
                    
                    for product_id in product_keys:
                        product = product_entities[product_id]
                        
                        # Extract basic product details
                        product_info = extract_product_info(product, term)
                        all_products.append(product_info)
                    
                    # Return the entire list of products with the total found
                    return all_products, total_found
                
                # Process just the first product for article searches
                elif product_keys:
                    product_id = product_keys[0]
                    product = product_entities[product_id]
                    
                    # Extract product details
                    try:
                        # Extract product details using helper function
                        product_info = extract_product_info(product, term)
                        return product_info, total_found
                    except RecursionError:
                        print(f"Recursion error processing product for term {term}")
                        # Return a simplified product
                        return {
                            "found": True,
                            "searchTerm": term,
                            "productId": product.get("productId"),
                            "name": product.get("name", "Product Name Unavailable"),
                            "brand": product.get("brand", "Brand Unavailable"),
                            "available": False,
                            "category": "",
                            "imageUrl": None,
                            "currentPrice": None,
                            "message": "Product data too complex to fully process"
                        }, 1
        
        # If we get here, no products were found
        return {
            "found": False,
            "searchTerm": term,
            "productId": None,
            "retailerProductId": None,
            "name": f"Article Not Found: {term}",
            "brand": None,
            "available": False,
            "category": "",
            "imageUrl": None,
            "notFoundMessage": f"The article \"{term}\" was not found. It may not be published yet or could be a typo."
        }, 0
    
    except RecursionError:
        print(f"Recursion error processing term {term}")
        return {
            "found": False,
            "searchTerm": term,
            "productId": None,
            "retailerProductId": None,
            "name": f"Processing Error: {term}",
            "brand": None,
            "available": False,
            "category": "",
            "imageUrl": None,
            "notFoundMessage": "Data too complex to process. Try a more specific search term."
        }, 0
    except Exception as e:
        print(f"Error processing term {term}: {str(e)}")
        # Return error as not found product
        return {
            "found": False,
            "searchTerm": term,
            "productId": None,
            "retailerProductId": None,
            "name": f"Article Not Found: {term}",
            "brand": None,
            "available": False,
            "category": "",
            "imageUrl": None,
            "notFoundMessage": f"Error processing the article. Please try again."
        }, 0
        
@app.route('/api/fetch-product', methods=['POST'])
def fetch_product():
    """API endpoint for product searches with user-provided session ID"""
    try:
        data = request.json
        
        if not data:
            return jsonify({"error": "No request data provided"}), 400

        search_term = data.get('searchTerm')
        session_id = data.get('sessionId')
        limit = data.get('limit', 'all')
        search_type = data.get('searchType', 'article')  # Default to article search
        
        # Determine if this is an article search or generic search
        is_article_search = search_type == 'article'

        if not search_term:
            return jsonify({"error": "Search term is required"}), 400

        if not session_id:
            return jsonify({"error": "Session ID is required"}), 400

        # Get region info from session ID
        region_info = get_region_info(session_id)
        
        if not region_info or not region_info.get("regionId"):
            return jsonify({"error": "Could not determine region from session ID"}), 400
            
        # Extract region name (use nickname or default to ID)
        region_name = region_info.get("nickname") or "Unknown Region"
        
        # Parse search terms using the enhanced parser that returns duplicate info
        individual_terms, duplicate_count, contains_ea_codes, duplicates = parse_search_terms(search_term)
        
        logging.info(f"Processing {len(individual_terms)} individual search terms (removed {duplicate_count} duplicates)")
        
        # For large sets of terms, use batched processing
        if len(individual_terms) > 30:
            # Define the function to generate streaming response
            def generate_response():
                products = []
                total_found = 0
                processed_count = 0
                batch_count = 0
                total_batches = (len(individual_terms) + BATCH_SIZE - 1) // BATCH_SIZE
                start_time = time.time()
                
                # Start the JSON response
                yield '{"region_name": %s, "region_info": %s, "search_term": %s, "parsed_terms": %s, "duplicate_count": %d, "duplicates": %s, "contains_ea_codes": %s, "search_type": %s, "status": "processing", "total_terms": %d, "total_batches": %d, "products": [' % (
                    json.dumps(region_name),
                    json.dumps(region_info),
                    json.dumps(search_term),
                    json.dumps(individual_terms),
                    duplicate_count,
                    json.dumps(duplicates),
                    json.dumps(contains_ea_codes),
                    json.dumps(search_type),
                    len(individual_terms),
                    total_batches
                )
                
                # Flag to track if we've written the first product
                first_product = True
                
                # Process terms in smaller batches to avoid memory issues
                for i in range(0, len(individual_terms), BATCH_SIZE):
                    batch_count += 1
                    batch_terms = individual_terms[i:i+BATCH_SIZE]
                    logging.info(f"Processing batch {batch_count}/{total_batches} with {len(batch_terms)} terms")
                    
                    # Send a batch progress update before processing
                    if i > 0:  # Skip for first batch to avoid extra comma
                        yield '], "progress_update": true, "batch_current": %d, "batch_total": %d, "processed": %d, "total": %d, "found": %d, "not_found": %d, "elapsed_time": %.2f, "status": "processing", "products": [' % (
                            batch_count,
                            total_batches,
                            processed_count,
                            len(individual_terms),
                            total_found,
                            processed_count - total_found,
                            time.time() - start_time,
                            # Added batch terms to help with debugging
                            # json.dumps(batch_terms[:3])  # Send first 3 terms in current batch
                        )
                        first_product = True  # Reset for new batch segment
                    
                    # Reduce number of concurrent threads for API requests
                    batch_workers = min(MAX_WORKERS, len(batch_terms))
                    batch_products = []
                    batch_total_found = 0
                    
                    with ThreadPoolExecutor(max_workers=batch_workers) as executor:
                        # Create a dictionary mapping futures to their corresponding terms
                        futures = {executor.submit(process_term, term, session_id, limit, is_article_search): term for term in batch_terms}
                        
                        # Process futures as they complete
                        for future in as_completed(futures):
                            term = futures[future]
                            processed_count += 1
                            
                            try:
                                product_result, term_total_found = future.result()
                                
                                # Update progress after each term (emit a special progress object)
                                if processed_count % 3 == 0 or processed_count == len(individual_terms):
                                    # Temporary yield to update progress without breaking JSON
                                    progress_percent = (processed_count / len(individual_terms)) * 100
                                    
                                    # Before adding a new product, close current array and add progress info
                                    if not first_product:
                                        yield '], "progress_update": true, "batch_current": %d, "batch_total": %d, "processed": %d, "total": %d, "found": %d, "not_found": %d, "progress_percent": %.1f, "elapsed_time": %.2f, "current_term": %s, "status": "processing", "products": [' % (
                                                batch_count,
                                                total_batches,
                                                processed_count,
                                                len(individual_terms),
                                                total_found + batch_total_found,
                                                processed_count - (total_found + batch_total_found),
                                                progress_percent,
                                                time.time() - start_time,
                                                json.dumps(term)
                                            )
                                        first_product = True
                                
                                # Handle both single product and list of products results
                                if isinstance(product_result, list):
                                    # For generic search that returns multiple products
                                    batch_total_found += term_total_found
                                    
                                    for idx, product_info in enumerate(product_result):
                                        if not first_product and idx == 0:
                                            yield ','
                                        elif idx > 0:
                                            yield ','
                                            
                                        if idx == 0:
                                            first_product = False
                                            
                                        # Yield the product as JSON
                                        yield json.dumps(product_info)
                                        batch_products.append(product_info)
                                elif product_result:  # Single product result
                                    batch_total_found += term_total_found
                                    
                                    # Add comma if not the first product
                                    if not first_product:
                                        yield ','
                                    first_product = False
                                    
                                    # Yield the product as JSON
                                    yield json.dumps(product_result)
                                    batch_products.append(product_result)
                                    
                            except Exception as e:
                                logging.error(f"Error processing term {term}: {str(e)}")
                                # Add not found entry for failed term
                                not_found_entry = {
                                    "found": False,
                                    "searchTerm": term,
                                    "productId": None,
                                    "retailerProductId": None,
                                    "name": f"Article Not Found: {term}",
                                    "brand": None,
                                    "available": False,
                                    "category": "",
                                    "imageUrl": None,
                                    "notFoundMessage": f"The article \"{term}\" was not found. It may not be published yet or could be a typo."
                                }
                                
                                # Add comma if not the first product
                                if not first_product:
                                    yield ','
                                first_product = False
                                
                                # Yield the not-found entry
                                yield json.dumps(not_found_entry)
                                batch_products.append(not_found_entry)
                    
                    # Run garbage collection after each batch to free memory
                    if GC_ENABLED:
                        collected = gc.collect()
                        logging.debug(f"Garbage collection: {collected} objects collected")
                    
                    # Add batch products to overall count but don't keep them in memory
                    # Just track the statistics to avoid large memory usage
                    total_found += batch_total_found
                    products_count = len(products) + len(batch_products)
                    
                    # After processing the batch, clear the references to free memory
                    batch_products.clear()
                    
                    # Slight delay between batches to prevent overwhelming the system
                    time.sleep(0.5)
                
                # Complete the JSON response
                yield '], "total_found": %d, "total_processed": %d, "status": "completed"}' % (
                    total_found,
                    processed_count
                )
                
            # Return a streaming response
            return Response(stream_with_context(generate_response()), content_type='application/json')
        
        # For smaller sets of terms, process everything at once
        else:
            # For smaller sets of terms, process everything at once
            all_products = []
            total_found = 0
            
            # Process terms in parallel
            with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(individual_terms))) as executor:
                futures = {executor.submit(process_term, term, session_id, limit, is_article_search): term for term in individual_terms}
                
                for future in as_completed(futures):
                    term = futures[future]
                    try:
                        product_result, term_total_found = future.result()
                        total_found += term_total_found
                        
                        if isinstance(product_result, list):
                            # For generic search that returns multiple products
                            all_products.extend(product_result)
                        elif product_result:
                            all_products.append(product_result)
                    except Exception as e:
                        logging.error(f"Error processing term {term}: {str(e)}")
                        # Add not found entry for failed term
                        all_products.append({
                            "found": False,
                            "searchTerm": term,
                            "productId": None,
                            "retailerProductId": None,
                            "name": f"Article Not Found: {term}",
                            "brand": None,
                            "available": False,
                            "category": "",
                            "imageUrl": None,
                            "notFoundMessage": f"The article \"{term}\" was not found. It may not be published yet or could be a typo."
                        })
            
            # Construct the response JSON
            response = {
                "region_name": region_name,
                "region_info": region_info,
                "search_term": search_term, 
                "parsed_terms": individual_terms,
                "duplicate_count": duplicate_count,
                "duplicates": duplicates,
                "contains_ea_codes": contains_ea_codes,
                "search_type": search_type,
                "total_found": total_found,
                "total_processed": len(individual_terms),
                "products": all_products
            }
            
            return jsonify(response)
            
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
