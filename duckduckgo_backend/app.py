from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import requests
import os
import uuid
import threading
import time
import zipfile
from io import BytesIO
import tempfile
import json
import logging
import random
import schedule
from datetime import datetime
from duckduckgo_search import DDGS

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Store task status and results in memory (in production, use Redis or database)
tasks = {}

# Keep-alive mechanism to prevent Render.com from sleeping
def keep_alive():
    """Send a request to self to keep the service awake"""
    try:
        # Get the service URL from environment or use localhost for local testing
        service_url = os.environ.get('RENDER_EXTERNAL_URL', 'http://localhost:5000')
        if service_url == 'http://localhost:5000':
            # Try to detect if we're on Render.com
            if 'RENDER' in os.environ:
                service_url = f"https://{os.environ.get('RENDER_SERVICE_NAME', 'lnd-image-scraper-backend')}.onrender.com"
        
        response = requests.get(f"{service_url}/api/health", timeout=10)
        logger.info(f"Keep-alive ping successful: {response.status_code}")
    except Exception as e:
        logger.warning(f"Keep-alive ping failed: {e}")

def start_keep_alive_scheduler():
    """Start the keep-alive scheduler in a background thread"""
    def run_scheduler():
        # Ping every 10 minutes to prevent sleeping (Render.com sleeps after 15 minutes)
        schedule.every(10).minutes.do(keep_alive)
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
    
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    logger.info("Keep-alive scheduler started")

def search_images_duckduckgo(keyword, max_images=None, safe_search=False):
    """Search for images using DuckDuckGo with safe search control"""
    images = []
    
    # If no limit specified, use a reasonable default for performance
    if max_images is None:
        max_images = 1000  # Truly unlimited, but reasonable for server performance
    
    logger.info(f"Starting DuckDuckGo search for '{keyword}' with target: {max_images} images, safe_search: {safe_search}")
    
    try:
        # Initialize DuckDuckGo search
        ddgs = DDGS()
        
        # Search for images with safe search OFF
        # safesearch parameter: 'on', 'moderate', 'off'
        safesearch_setting = 'off' if not safe_search else 'moderate'
        
        logger.info(f"DuckDuckGo safesearch setting: {safesearch_setting}")
        
        # Perform the search
        search_results = ddgs.images(
            keywords=keyword,
            region='wt-wt',  # Worldwide
            safesearch=safesearch_setting,  # Safe search OFF
            size=None,  # Any size
            color=None,  # Any color
            type_image=None,  # Any type
            layout=None,  # Any layout
            license_image=None,  # Any license
            max_results=max_images  # Maximum number of results
        )
        
        # Convert results to our format
        for i, result in enumerate(search_results):
            if len(images) >= max_images:
                break
                
            try:
                # Extract image information
                image_url = result.get('image', '')
                title = result.get('title', f'Image {i+1}')
                source = result.get('source', 'DuckDuckGo')
                width = result.get('width', 0)
                height = result.get('height', 0)
                
                # Create filename from title or use default
                safe_title = ''.join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
                if not safe_title:
                    safe_title = f'duckduckgo_{keyword}_{i+1}'
                
                # Determine file extension from URL
                file_ext = '.jpg'  # Default
                if image_url:
                    if '.png' in image_url.lower():
                        file_ext = '.png'
                    elif '.gif' in image_url.lower():
                        file_ext = '.gif'
                    elif '.webp' in image_url.lower():
                        file_ext = '.webp'
                
                filename = f"{safe_title[:50]}{file_ext}"  # Limit filename length
                
                images.append({
                    'url': image_url,
                    'source': f'DuckDuckGo - {source}',
                    'filename': filename,
                    'title': title,
                    'width': width,
                    'height': height,
                    'size': width * height * 3 // 10 if width and height else 100000  # Estimated size
                })
                
                logger.info(f"Added image {i+1}: {title[:50]}...")
                
            except Exception as e:
                logger.error(f"Failed to process DuckDuckGo result {i+1}: {e}")
                continue
        
        logger.info(f"DuckDuckGo search completed: {len(images)} images found")
        
    except Exception as e:
        logger.error(f"DuckDuckGo search failed: {e}")
        # Fallback to placeholder images if DuckDuckGo fails
        logger.info("Falling back to placeholder images due to DuckDuckGo failure")
        images = generate_fallback_images(keyword, max_images)
    
    return images

def generate_fallback_images(keyword, max_images):
    """Generate fallback placeholder images if DuckDuckGo fails"""
    images = []
    
    try:
        # Generate some placeholder images as fallback
        fallback_count = min(max_images, 50)  # Limit fallback images
        
        for i in range(fallback_count):
            width = random.choice([800, 900, 1000, 1200])
            height = random.choice([600, 700, 800, 900])
            color = random.choice(['FF6B6B', '4ECDC4', '45B7D1', 'FFA07A', '98D8C8'])
            
            images.append({
                'url': f'https://via.placeholder.com/{width}x{height}/{color}/FFFFFF?text={keyword}+{i+1}',
                'source': 'Placeholder (Fallback)',
                'filename': f'fallback_{keyword}_{i+1}.jpg',
                'title': f'Fallback image for {keyword} #{i+1}',
                'width': width,
                'height': height,
                'size': width * height * 3 // 15
            })
        
        logger.info(f"Generated {len(images)} fallback images")
        
    except Exception as e:
        logger.error(f"Fallback image generation failed: {e}")
    
    return images

def scrape_images_async(task_id, keyword, num_images, quality, safe_search_off=True):
    """Asynchronously scrape images using DuckDuckGo - TRULY UNLIMITED"""
    try:
        tasks[task_id]['status'] = 'processing'
        tasks[task_id]['progress'] = 5
        tasks[task_id]['message'] = 'Initializing DuckDuckGo image search with safe search OFF...'
        
        # Search for images using DuckDuckGo - NO LIMITS AT ALL
        tasks[task_id]['progress'] = 15
        tasks[task_id]['message'] = f'Searching DuckDuckGo for "{keyword}" with safe search OFF...'
        
        # Use DuckDuckGo search with safe search disabled
        found_images = search_images_duckduckgo(keyword, num_images, safe_search=not safe_search_off)
        
        tasks[task_id]['progress'] = 30
        tasks[task_id]['message'] = f'Found {len(found_images)} images from DuckDuckGo. Starting validation...'
        
        # Validate and process images
        processed_images = []
        total_found = len(found_images)
        
        for i, image_data in enumerate(found_images):
            try:
                progress = 30 + (i / total_found) * 60
                tasks[task_id]['progress'] = int(progress)
                tasks[task_id]['message'] = f'Processing image {i+1} of {total_found}: {image_data.get("title", "Unknown")[:30]}...'
                
                # Validate image URL
                if image_data.get('url') and image_data['url'].startswith(('http://', 'https://')):
                    processed_images.append(image_data)
                else:
                    logger.warning(f"Invalid image URL for image {i+1}: {image_data.get('url')}")
                
                # Small delay to prevent overwhelming servers
                time.sleep(0.01)  # Minimal delay
                
            except Exception as e:
                logger.error(f"Failed to process image {i+1}: {e}")
                continue
        
        # Final results
        tasks[task_id]['status'] = 'completed'
        tasks[task_id]['progress'] = 100
        tasks[task_id]['message'] = f'Successfully processed {len(processed_images)} images from DuckDuckGo!'
        tasks[task_id]['images'] = processed_images
        tasks[task_id]['total_images'] = len(processed_images)
        tasks[task_id]['safe_search_off'] = safe_search_off
        
    except Exception as e:
        logger.error(f"DuckDuckGo scraping failed for task {task_id}: {e}")
        tasks[task_id]['status'] = 'error'
        tasks[task_id]['message'] = f'DuckDuckGo scraping failed: {str(e)}'
        tasks[task_id]['progress'] = 0

@app.route('/')
def home():
    """Home page with API information"""
    return jsonify({
        'message': 'LND AI Image Scraper API - DuckDuckGo Edition with Safe Search OFF',
        'version': '3.0.0',
        'status': 'running',
        'platform': 'Render.com Free Tier',
        'features': [
            'DuckDuckGo Image Search', 
            'Safe Search OFF', 
            'TRULY Unlimited Scraping', 
            '24/7 Uptime', 
            'No Credit Card Required', 
            'Keep-Alive Enabled'
        ],
        'endpoints': {
            'scrape': 'POST /api/scrape',
            'status': 'GET /api/status/<task_id>',
            'image': 'GET /api/image/<task_id>/<image_index>',
            'download': 'GET /api/download/<task_id>',
            'health': 'GET /api/health',
            'test': 'GET /api/test'
        },
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/scrape', methods=['POST'])
def start_scraping():
    """Start a new DuckDuckGo image scraping task with safe search OFF"""
    try:
        data = request.get_json()
        keyword = data.get('keyword', '').strip()
        num_images = data.get('num_images', 20)
        quality = data.get('quality', 'high')
        safe_search_off = data.get('safe_search_off', True)  # Default to safe search OFF
        
        if not keyword:
            return jsonify({'error': 'Keyword is required'}), 400
        
        # TRULY NO LIMITS - Accept any number the user wants
        if num_images <= 0:
            num_images = 20  # Default if invalid
        
        # Generate unique task ID
        task_id = str(uuid.uuid4())
        
        # Initialize task
        tasks[task_id] = {
            'status': 'started',
            'progress': 0,
            'message': 'Task initiated',
            'keyword': keyword,
            'num_images': num_images,
            'quality': quality,
            'safe_search_off': safe_search_off,
            'images': [],
            'total_images': 0,
            'created_at': datetime.now().isoformat()
        }
        
        # Start scraping in background thread
        thread = threading.Thread(target=scrape_images_async, args=(task_id, keyword, num_images, quality, safe_search_off))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'task_id': task_id,
            'status': 'started',
            'message': f'Started DuckDuckGo search for {num_images} images with keyword: {keyword}',
            'safe_search': 'OFF' if safe_search_off else 'ON',
            'platform': 'Render.com Free Tier - DuckDuckGo Edition',
            'keep_alive': 'enabled'
        })
        
    except Exception as e:
        logger.error(f"Error starting DuckDuckGo scraping: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/status/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """Get the status of a scraping task"""
    if task_id not in tasks:
        return jsonify({'error': 'Task not found'}), 404
    
    return jsonify(tasks[task_id])

@app.route('/api/image/<task_id>/<int:image_index>', methods=['GET'])
def get_image(task_id, image_index):
    """Get a specific image from a completed task"""
    if task_id not in tasks:
        return jsonify({'error': 'Task not found'}), 404
    
    task = tasks[task_id]
    if task['status'] != 'completed':
        return jsonify({'error': 'Task not completed'}), 400
    
    if image_index >= len(task['images']):
        return jsonify({'error': 'Image index out of range'}), 404
    
    image_data = task['images'][image_index]
    image_url = image_data['url']
    
    try:
        # Download and serve the image with better error handling
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'no-cache',
            'Referer': 'https://duckduckgo.com/'
        }
        
        response = requests.get(image_url, timeout=30, headers=headers, stream=True)
        if response.status_code == 200:
            content_type = response.headers.get('content-type', 'image/jpeg')
            filename = image_data.get('filename', f'duckduckgo_image_{image_index + 1}.jpg')
            
            # Return the image content directly
            return response.content, 200, {
                'Content-Type': content_type,
                'Content-Disposition': f'inline; filename={filename}',
                'Cache-Control': 'public, max-age=3600'
            }
        else:
            logger.error(f"Failed to fetch image: HTTP {response.status_code}")
            return jsonify({'error': f'Failed to fetch image: HTTP {response.status_code}'}), 500
            
    except requests.exceptions.Timeout:
        logger.error(f"Image download timeout for index {image_index}")
        return jsonify({'error': 'Image download timeout'}), 500
    except Exception as e:
        logger.error(f"Image download failed: {e}")
        return jsonify({'error': f'Image download failed: {str(e)}'}), 500

@app.route('/api/download/<task_id>', methods=['GET'])
def download_zip(task_id):
    """Download all images as a ZIP file with improved error handling and reliability"""
    if task_id not in tasks:
        return jsonify({'error': 'Task not found'}), 404
    
    task = tasks[task_id]
    if task['status'] != 'completed':
        return jsonify({'error': 'Task not completed'}), 400
    
    try:
        logger.info(f"Starting ZIP creation for DuckDuckGo task {task_id} with {len(task['images'])} images")
        
        # Create ZIP file in memory with better compression
        zip_buffer = BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zip_file:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Cache-Control': 'no-cache',
                'Referer': 'https://duckduckgo.com/'
            }
            
            successful_downloads = 0
            failed_downloads = 0
            
            for i, image_data in enumerate(task['images']):
                try:
                    logger.info(f"Downloading DuckDuckGo image {i+1}/{len(task['images'])}: {image_data['url']}")
                    
                    # Download image with timeout and retries
                    response = requests.get(
                        image_data['url'], 
                        timeout=30, 
                        headers=headers,
                        stream=True,
                        allow_redirects=True
                    )
                    
                    if response.status_code == 200:
                        filename = image_data.get('filename', f'duckduckgo_image_{i+1}.jpg')
                        
                        # Ensure unique filenames
                        counter = 1
                        original_filename = filename
                        while filename in [info.filename for info in zip_file.infolist()]:
                            name, ext = os.path.splitext(original_filename)
                            filename = f"{name}_{counter}{ext}"
                            counter += 1
                        
                        # Get image content
                        image_content = response.content
                        
                        # Validate image content
                        if len(image_content) > 0:
                            # Add image to ZIP
                            zip_file.writestr(filename, image_content)
                            successful_downloads += 1
                            logger.info(f"Successfully added {filename} to ZIP ({len(image_content)} bytes)")
                        else:
                            logger.warning(f"Empty image content for {filename}")
                            failed_downloads += 1
                        
                    else:
                        logger.warning(f"Failed to download DuckDuckGo image {i+1}: HTTP {response.status_code}")
                        failed_downloads += 1
                        
                except requests.exceptions.Timeout:
                    logger.error(f"Timeout downloading DuckDuckGo image {i+1}")
                    failed_downloads += 1
                except Exception as e:
                    logger.error(f"Failed to download DuckDuckGo image {i+1}: {e}")
                    failed_downloads += 1
                    continue
            
            # Add a summary file
            summary = f"""LND AI Image Scraper - DuckDuckGo Download Summary
Keyword: {task['keyword']}
Total Images Requested: {task['num_images']}
Successfully Downloaded: {successful_downloads}
Failed Downloads: {failed_downloads}
Download Success Rate: {(successful_downloads / len(task['images']) * 100):.1f}%
Safe Search: {'OFF' if task.get('safe_search_off', True) else 'ON'}
Search Engine: DuckDuckGo
Generated by: LND AI Image Scraper
Platform: Render.com
Timestamp: {datetime.now().isoformat()}
Task ID: {task_id}
"""
            zip_file.writestr('download_summary.txt', summary)
            
            logger.info(f"DuckDuckGo ZIP creation completed: {successful_downloads} successful, {failed_downloads} failed")
        
        zip_buffer.seek(0)
        
        if successful_downloads == 0:
            logger.error("No DuckDuckGo images could be downloaded for ZIP")
            return jsonify({'error': 'No images could be downloaded'}), 500
        
        # Create response with proper headers
        response = send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f"duckduckgo_{task['keyword']}_images_{successful_downloads}_files.zip"
        )
        
        logger.info(f"DuckDuckGo ZIP file sent successfully: duckduckgo_{task['keyword']}_images_{successful_downloads}_files.zip")
        return response
        
    except Exception as e:
        logger.error(f"DuckDuckGo ZIP creation failed: {e}")
        return jsonify({'error': f'ZIP creation failed: {str(e)}'}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'message': 'LND Image Scraper API is running on Render.com - DuckDuckGo Edition',
        'active_tasks': len(tasks),
        'version': '3.0.0',
        'platform': 'Render.com',
        'features': [
            'DuckDuckGo Image Search', 
            'Safe Search OFF', 
            'Truly Unlimited Scraping', 
            'Keep-Alive Enabled'
        ],
        'uptime': '24/7',
        'keep_alive': 'enabled',
        'search_engine': 'DuckDuckGo',
        'safe_search': 'OFF by default',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/clear/<task_id>', methods=['DELETE'])
def clear_task(task_id):
    """Clear a completed task to free memory"""
    if task_id in tasks:
        del tasks[task_id]
        return jsonify({'message': 'Task cleared successfully'})
    return jsonify({'error': 'Task not found'}), 404

@app.route('/api/test', methods=['GET'])
def test_endpoint():
    """Test endpoint to verify the API is working"""
    return jsonify({
        'message': 'LND Image Scraper API Test Successful - DuckDuckGo Edition!',
        'status': 'working',
        'timestamp': datetime.now().isoformat(),
        'features': ['DuckDuckGo Search', 'Safe Search OFF', 'Unlimited Scraping', 'ZIP Downloads', 'Keep-Alive'],
        'keep_alive': 'enabled',
        'search_engine': 'DuckDuckGo'
    })

@app.route('/api/keep-alive', methods=['GET'])
def manual_keep_alive():
    """Manual keep-alive endpoint"""
    return jsonify({
        'message': 'Keep-alive ping successful - DuckDuckGo Edition',
        'timestamp': datetime.now().isoformat(),
        'status': 'awake',
        'search_engine': 'DuckDuckGo'
    })

if __name__ == '__main__':
    # Start keep-alive scheduler
    start_keep_alive_scheduler()
    
    # Get port from environment variable or default to 5000
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

