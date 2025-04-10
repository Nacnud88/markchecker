from flask import Flask, request, jsonify, render_template
import requests
import traceback
import json
import time
import random
import re  # Import for regex pattern matching

app = Flask(__name__, static_folder="static", template_folder="templates")

@app.route('/')
def index():
    """Serve the main HTML page"""
    return render_template('index.html')

def get_region_info(session_id):
    """Get region ID and details from Voila API using session ID"""
    try:
        url = "https://voila.ca/api/cart/v1/carts/active"
        
        headers = {
            "accept": "application/json; charset=utf-8",
            "client-route-id": "d55f7f13-4217-4320-907e-eadd09051a7c"
        }
        
        cookies = {
            "global_sid": session_id
        }
        
        response = requests.get(url, headers=headers, cookies=cookies)
        
        if response.status_code == 200:
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
                    
            return region_info
        
        # Return None if there was an error
        return None
    
    except Exception as e:
        print(f"Error getting region info: {str(e)}")
        return None

def parse_search_terms(search_input):
    """
    Parse search input into individual search terms.
    Handles comma-separated, newline-separated, and space-separated inputs.
    Also handles EA-code pattern recognition.
    """
    # First try comma or newline separation
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
        else:
            # Otherwise, try splitting by spaces if the input is particularly long
            if len(search_input) > 50 and ' ' in search_input:
                terms = search_input.split()
            else:
                # Use the entire input as a single term
                terms = [search_input]
    
    # Clean up terms
    terms = [term.strip() for term in terms if term.strip()]
    
    return terms

@app.route('/api/fetch-product', methods=['POST'])
def fetch_product():
    """API endpoint for product searches with user-provided session ID"""
    data = request.json

    if not data:
        return jsonify({"error": "No request data provided"}), 400

    search_term = data.get('searchTerm')
    session_id = data.get('sessionId')
    limit = data.get('limit', 'all')

    if not search_term:
        return jsonify({"error": "Search term is required"}), 400

    if not session_id:
        return jsonify({"error": "Session ID is required"}), 400

    try:
        # Get region info from session ID
        region_info = get_region_info(session_id)
        
        if not region_info or not region_info.get("regionId"):
            return jsonify({"error": "Could not determine region from session ID"}), 400
            
        # Extract region name (use nickname or default to ID)
        region_name = region_info.get("nickname") or "Unknown Region"
        
        # Parse search terms using the enhanced parser
        individual_terms = parse_search_terms(search_term)
        
        print(f"Parsed {len(individual_terms)} individual search terms")
        
        # Handle individual search terms
        products = []
        total_found = 0
        not_found_terms = []  # Track terms that weren't found
        
        for term in individual_terms:
            term = term.strip()
            if not term:
                continue
                
            # Fetch data from Voila API
            raw_data = fetch_product_data(term, session_id)
            
            term_products = []
            
            if raw_data and "entities" in raw_data and "product" in raw_data["entities"]:
                product_entities = raw_data["entities"]["product"]
                
                if product_entities:  # Products found for this term
                    total_found += len(product_entities)
                    
                    # Apply limit if needed
                    if limit != 'all':
                        try:
                            max_items = int(limit) if isinstance(limit, str) else limit
                            product_keys = list(product_entities.keys())[:max_items]
                        except (ValueError, TypeError):
                            product_keys = product_entities.keys()
                    else:
                        product_keys = product_entities.keys()
                    
                    # Extract product info for each item
                    for product_id in product_keys:
                        product = product_entities[product_id]
                        
                        # Extract product details
                        product_info = {
                            "found": True,
                            "searchTerm": term,  # Add search term to each product
                            "productId": product.get("productId"),
                            "retailerProductId": product.get("retailerProductId"),
                            "name": product.get("name"),
                            "brand": product.get("brand"),
                            "available": product.get("available", False),
                            "category": " > ".join(product.get("categoryPath", [])) if "categoryPath" in product else "",
                            "imageUrl": product.get("image", {}).get("src"),
                            "currency": product.get("price", {}).get("current", {}).get("currency", "CAD")
                        }
                        
                        # Handle price information
                        if "price" in product:
                            price_info = product["price"]
                            
                            # Current price
                            if "current" in price_info:
                                product_info["currentPrice"] = price_info["current"].get("amount")
                                
                            # Original price
                            if "original" in price_info:
                                product_info["originalPrice"] = price_info["original"].get("amount")
                                
                                # Calculate discount percentage if both prices are available
                                if (product_info["currentPrice"] is not None and 
                                    product_info["originalPrice"] is not None):
                                    try:
                                        # Convert to float before calculation
                                        current_price = float(product_info["currentPrice"])
                                        original_price = float(product_info["originalPrice"])
                                        
                                        if original_price > current_price:
                                            discount = ((original_price - current_price) / original_price * 100)
                                            product_info["discountPercentage"] = round(discount)
                                    except (ValueError, TypeError):
                                        # Handle cases where conversion to float fails
                                        pass
                                        
                            # Unit price
                            if "unit" in price_info:
                                product_info["unitPrice"] = price_info["unit"].get("current", {}).get("amount")
                                product_info["unitLabel"] = price_info["unit"].get("label")
                                
                        # Extract offers
                        if "offers" in product:
                            product_info["offers"] = product.get("offers", [])
                            
                        if "offer" in product:
                            product_info["primaryOffer"] = product.get("offer")
                            
                        term_products.append(product_info)
                else:
                    # No products found for this term
                    not_found_terms.append(term)
            else:
                # API error or no results
                not_found_terms.append(term)
                
            # Add this term's products to the main list
            products.extend(term_products)
            
        # Add not found entries to products list
        for term in not_found_terms:
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
            products.append(not_found_entry)

        # Return the processed data with region information
        response = {
            "region_name": region_name,
            "region_info": region_info,  # Include detailed region info
            "search_term": search_term,
            "parsed_terms": individual_terms,  # Include the parsed terms for debugging
            "total_found": total_found,
            "not_found_terms": not_found_terms,
            "products": products
        }

        return jsonify(response)

    except Exception as e:
        traceback.print_exc()  # Print the full error traceback for debugging
        return jsonify({"error": str(e)}), 500

@app.route('/api/auto-scrape', methods=['POST'])
def auto_scrape():
    """Automatically scrape product data from Voila.ca"""
    data = request.json

    if not data:
        return jsonify({"error": "No data provided"}), 400

    session_id = data.get('sessionId')
    category = data.get('category', 'flyer')  # Default to flyer
    max_products = data.get('maxProducts', 100)  # Default limit to prevent overloading

    if not session_id:
        return jsonify({"error": "Session ID is required"}), 400

    try:
        # Get region info from session ID
        region_info = get_region_info(session_id)
        
        if not region_info or not region_info.get("regionId"):
            return jsonify({"error": "Could not determine region from session ID"}), 400
            
        # Extract region name (use nickname or default to ID)
        region_name = region_info.get("nickname") or "Unknown Region"
        
        # Collection of products from different methods
        scraped_products = []

        # Try different scraping approaches
        if category == 'flyer':
            # Try multiple methods to get flyer products
            flyer_products = scrape_flyer_products(session_id, max_products)
            if flyer_products:
                scraped_products.extend(flyer_products)

            # If no products found, try alternative method
            if not scraped_products:
                flyer_category_products = scrape_category_by_name(session_id, "FLYER & DEALS", max_products)
                if flyer_category_products:
                    scraped_products.extend(flyer_category_products)

        elif category == 'deals':
            # Try multiple methods to get deals
            deals_products = scrape_deals(session_id, max_products)
            if deals_products:
                scraped_products.extend(deals_products)

            # If no products found, try alternative methods
            if not scraped_products:
                scene_products = scrape_category_by_name(session_id, "Scene+ Deals", max_products)
                if scene_products:
                    scraped_products.extend(scene_products)

            if len(scraped_products) < max_products:
                sale_products = scrape_search_term(session_id, "sale", max_products - len(scraped_products))
                if sale_products:
                    # Filter for products with offers
                    sale_products_with_offers = [p for p in sale_products if p.get("offers") or p.get("originalPrice")]
                    scraped_products.extend(sale_products_with_offers)

        elif category == 'popular':
            popular_products = scrape_popular_products(session_id, max_products)
            if popular_products:
                scraped_products.extend(popular_products)

            # If no products found, try alternative methods
            if not scraped_products:
                # Try basic searches for common items
                basic_terms = ["milk", "bread", "eggs", "banana", "apple"]
                for term in basic_terms:
                    if len(scraped_products) < max_products:
                        term_products = scrape_search_term(session_id, term, 10)
                        if term_products:
                            scraped_products.extend(term_products[:max_products - len(scraped_products)])

        else:
            # Handle custom category
            # First try direct category search
            custom_products = scrape_category_by_name(session_id, category, max_products)
            if custom_products:
                scraped_products.extend(custom_products)

            # If that fails, try it as a search term
            if not scraped_products:
                search_products = scrape_search_term(session_id, category, max_products)
                if search_products:
                    scraped_products.extend(search_products)

        # Deduplicate products by retailerProductId
        unique_products = {}
        for product in scraped_products:
            retailer_id = product.get("retailerProductId")
            if retailer_id and retailer_id not in unique_products:
                unique_products[retailer_id] = product

        # Convert back to list and limit to max_products
        final_products = list(unique_products.values())[:max_products]

        # Debug information
        debug_info = {
            "scraping_methods_tried": [],
            "api_responses": {}
        }

        response = {
            "region_name": region_name,
            "region_info": region_info,  # Include detailed region info
            "category": category,
            "total_products": len(final_products),
            "products": final_products,
            "debug_info": debug_info
        }

        return jsonify(response)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

def scrape_flyer_products(session_id, max_products=100):
    """Scrape flyer products from Voila.ca"""
    products = []

    try:
        # First, get the current flyer ID
        flyer_id = get_current_flyer_id(session_id)

        if not flyer_id:
            print("No flyer ID found, trying alternative approach")
            return []

        print(f"Found flyer ID: {flyer_id}")

        # Fetch flyer page data
        url = f"https://voila.ca/api/v6/flyers/{flyer_id}/pages"

        headers = {
            "accept": "application/json; charset=utf-8",
            "client-route-id": "5fa0016c-9764-4e09-9738-12c33fb47fc2"
        }

        cookies = {
            "global_sid": session_id
        }

        response = requests.get(url, headers=headers, cookies=cookies)

        if response.status_code == 200:
            pages_data = response.json()

            # Get all page IDs
            page_ids = []
            if "result" in pages_data and "pages" in pages_data["result"]:
                page_ids = [page.get("id") for page in pages_data["result"]["pages"] if page.get("id")]

            # Fetch products from each page
            for page_id in page_ids:
                if len(products) >= max_products:
                    break

                page_products = get_flyer_page_products(session_id, flyer_id, page_id, max_products - len(products))
                if page_products:
                    products.extend(page_products)

    except Exception as e:
        print(f"Error scraping flyer products: {str(e)}")
        traceback.print_exc()

    return products

def get_flyer_page_products(session_id, flyer_id, page_id, max_products=50):
    """Get products from a specific flyer page"""
    products = []

    try:
        url = f"https://voila.ca/api/v6/flyers/{flyer_id}/pages/{page_id}"

        headers = {
            "accept": "application/json; charset=utf-8",
            "client-route-id": "5fa0016c-9764-4e09-9738-12c33fb47fc2"
        }

        cookies = {
            "global_sid": session_id
        }

        response = requests.get(url, headers=headers, cookies=cookies)

        if response.status_code == 200:
            page_data = response.json()

            # Extract products from page data
            if "entities" in page_data and "product" in page_data["entities"]:
                products_data = page_data["entities"]["product"]

                for product_id, product in products_data.items():
                    # Process product and add to list
                    processed_product = process_product(product)
                    if processed_product:
                        products.append(processed_product)

                        # Check if we've reached the max products limit
                        if len(products) >= max_products:
                            break

    except Exception as e:
        print(f"Error getting flyer page products: {str(e)}")

    return products

def scrape_deals(session_id, max_products=100):
    """Scrape deals from Voila.ca"""
    products = []

    try:
        url = "https://voila.ca/api/v6/deals"

        headers = {
            "accept": "application/json; charset=utf-8",
            "client-route-id": "5fa0016c-9764-4e09-9738-12c33fb47fc2"
        }

        cookies = {
            "global_sid": session_id
        }

        response = requests.get(url, headers=headers, cookies=cookies)

        if response.status_code == 200:
            deals_data = response.json()

            # Extract products from deals data
            if "entities" in deals_data and "product" in deals_data["entities"]:
                products_data = deals_data["entities"]["product"]

                for product_id, product in products_data.items():
                    # Process product and add to list
                    processed_product = process_product(product)
                    if processed_product:
                        products.append(processed_product)

                        # Check if we've reached the max products limit
                        if len(products) >= max_products:
                            break

    except Exception as e:
        print(f"Error scraping deals: {str(e)}")
        traceback.print_exc()

    return products

def scrape_popular_products(session_id, max_products=100):
    """Scrape popular products from Voila.ca"""
    products = []

    try:
        url = "https://voila.ca/api/v6/popular-products"

        headers = {
            "accept": "application/json; charset=utf-8",
            "client-route-id": "5fa0016c-9764-4e09-9738-12c33fb47fc2"
        }

        cookies = {
            "global_sid": session_id
        }

        response = requests.get(url, headers=headers, cookies=cookies)

        if response.status_code == 200:
            popular_data = response.json()

            # Extract products from popular data
            if "entities" in popular_data and "product" in popular_data["entities"]:
                products_data = popular_data["entities"]["product"]

                for product_id, product in products_data.items():
                    # Process product and add to list
                    processed_product = process_product(product)
                    if processed_product:
                        products.append(processed_product)

                        # Check if we've reached the max products limit
                        if len(products) >= max_products:
                            break

    except Exception as e:
        print(f"Error scraping popular products: {str(e)}")
        traceback.print_exc()

    return products

def scrape_category_by_name(session_id, category_name, max_products=100):
    """Scrape products from a category by name"""
    products = []

    try:
        # First, search for category ID by name
        categories = get_categories(session_id)
        category_id = None

        for cat in categories:
            if cat.get("name") and category_name.lower() in cat.get("name").lower():
                category_id = cat.get("id")
                break

        if not category_id:
            print(f"Category not found: {category_name}")
            return []

        print(f"Found category ID: {category_id} for {category_name}")

        # Now get products from this category
        url = f"https://voila.ca/api/v6/categories/{category_id}/products"

        headers = {
            "accept": "application/json; charset=utf-8",
            "client-route-id": "5fa0016c-9764-4e09-9738-12c33fb47fc2"
        }

        cookies = {
            "global_sid": session_id
        }

        # Parameters for pagination
        params = {
            "page": 1,
            "size": 50
        }

        while len(products) < max_products:
            response = requests.get(url, headers=headers, cookies=cookies, params=params)

            if response.status_code == 200:
                category_data = response.json()

                # Extract products from category data
                if "entities" in category_data and "product" in category_data["entities"]:
                    products_data = category_data["entities"]["product"]

                    if not products_data:  # No more products
                        break

                    for product_id, product in products_data.items():
                        # Process product and add to list
                        processed_product = process_product(product)
                        if processed_product:
                            products.append(processed_product)

                            # Check if we've reached the max products limit
                            if len(products) >= max_products:
                                break

                # Move to the next page
                params["page"] += 1

                # Add a small delay to avoid overwhelming the server
                time.sleep(0.2)
            else:
                # Error or no more pages
                break

    except Exception as e:
        print(f"Error scraping category: {str(e)}")
        traceback.print_exc()

    return products

def scrape_search_term(session_id, search_term, max_products=100):
    """Scrape products by searching for a term"""
    products = []

    try:
        raw_data = fetch_product_data(search_term, session_id)

        if raw_data and "entities" in raw_data and "product" in raw_data["entities"]:
            products_data = raw_data["entities"]["product"]

            product_count = 0
            for product_id, product in products_data.items():
                if product_count >= max_products:
                    break

                processed_product = process_product(product)
                if processed_product:
                    products.append(processed_product)
                    product_count += 1

    except Exception as e:
        print(f"Error scraping search term: {str(e)}")
        traceback.print_exc()

    return products

def get_categories(session_id):
    """Get all categories from Voila.ca"""
    categories = []

    try:
        url = "https://voila.ca/api/v6/categories"

        headers = {
            "accept": "application/json; charset=utf-8",
            "client-route-id": "5fa0016c-9764-4e09-9738-12c33fb47fc2"
        }

        cookies = {
            "global_sid": session_id
        }

        response = requests.get(url, headers=headers, cookies=cookies)

        if response.status_code == 200:
            categories_data = response.json()

            if "result" in categories_data and "categories" in categories_data["result"]:
                return categories_data["result"]["categories"]

    except Exception as e:
        print(f"Error getting categories: {str(e)}")

    return categories

def get_current_flyer_id(session_id):
    """Get the current flyer ID from Voila.ca"""
    try:
        url = "https://voila.ca/api/v6/flyers"

        headers = {
            "accept": "application/json; charset=utf-8",
            "client-route-id": "5fa0016c-9764-4e09-9738-12c33fb47fc2"
        }

        cookies = {
            "global_sid": session_id
        }

        response = requests.get(url, headers=headers, cookies=cookies)
        print(f"Flyer API response status: {response.status_code}")

        if response.status_code == 200:
            flyers_data = response.json()

            # Find the current active flyer
            if "result" in flyers_data and "flyers" in flyers_data["result"]:
                for flyer in flyers_data["result"]["flyers"]:
                    if flyer.get("status") == "ACTIVE":
                        return flyer.get("id")

                # If we didn't find an active one, just use the first one
                if flyers_data["result"]["flyers"]:
                    return flyers_data["result"]["flyers"][0].get("id")

            print("No flyers found in API response")
            print(json.dumps(flyers_data, indent=2))

    except Exception as e:
        print(f"Error getting flyer ID: {str(e)}")
        traceback.print_exc()

    return None

def process_product(product):
    """Process a product from the API response"""
    if not product:
        return None

    # Extract basic product details
    product_info = {
        "found": True,  # Flag to indicate this is a found product
        "productId": product.get("productId"),
        "retailerProductId": product.get("retailerProductId"),
        "name": product.get("name"),
        "brand": product.get("brand"),
        "available": product.get("available", False),
        "category": " > ".join(product.get("categoryPath", [])) if "categoryPath" in product else "",
        "imageUrl": product.get("image", {}).get("src") if "image" in product else None,
        "offers": []
    }

    # Handle price information
    if "price" in product:
        price_info = product["price"]

        # Current price
        if "current" in price_info:
            product_info["currentPrice"] = price_info["current"].get("amount")
            product_info["currency"] = price_info["current"].get("currency", "CAD")

        # Original price
        if "original" in price_info:
            product_info["originalPrice"] = price_info["original"].get("amount")

            # Calculate discount percentage if both prices are available
            if ("currentPrice" in product_info and "originalPrice" in product_info and
                product_info["currentPrice"] is not None and product_info["originalPrice"] is not None):
                try:
                    # Convert to float before calculation
                    current_price = float(product_info["currentPrice"])
                    original_price = float(product_info["originalPrice"])

                    if original_price > current_price:
                        discount = ((original_price - current_price) / original_price * 100)
                        product_info["discountPercentage"] = round(discount)
                except (ValueError, TypeError):
                    # Handle cases where conversion to float fails
                    pass

        # Unit price
        if "unit" in price_info:
            product_info["unitPrice"] = price_info["unit"].get("current", {}).get("amount")
            product_info["unitLabel"] = price_info["unit"].get("label")

    # Extract offers
    if "offers" in product:
        product_info["offers"] = product.get("offers", [])

    # Extract primary offer
    if "offer" in product:
        product_info["primaryOffer"] = product.get("offer")
        if product_info["primaryOffer"] and product_info["primaryOffer"] not in product_info["offers"]:
            product_info["offers"].append(product_info["primaryOffer"])

    return product_info

def fetch_product_data(product_id, session_id):
    """Fetch product data from Voila.ca API using the provided session ID"""
    url = "https://voila.ca/api/v6/products/search"

    headers = {
        "accept": "application/json; charset=utf-8",
        "client-route-id": "5fa0016c-9764-4e09-9738-12c33fb47fc2"
    }

    cookies = {
        "global_sid": session_id
    }

    params = {
        "term": product_id
    }

    response = requests.get(url, headers=headers, params=params, cookies=cookies)

    if response.status_code != 200:
        raise Exception(f"API returned status code {response.status_code}")

    return response.json()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
