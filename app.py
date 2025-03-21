from flask import Flask, request, jsonify, render_template, Response
import os
import mimetypes
import time
import requests
import concurrent.futures
import threading
import uuid
import json
from queue import Queue
import io
from dotenv import load_dotenv
import logging
from logging.handlers import RotatingFileHandler

# Load environment variables from .env file
load_dotenv()

# Set up logging
if not os.path.exists('logs'):
    os.mkdir('logs')
file_handler = RotatingFileHandler('logs/knowledge_uploader.log', maxBytes=10240, backupCount=10)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
file_handler.setLevel(logging.INFO)

# Configure app
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max upload size
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'dev-key-for-non-production'

# Set up logging
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
app.logger.info('Knowledge Folder Uploader startup')

# Dictionary to store upload sessions
active_uploads = {}
# Stores event queues for each session
event_queues = {}

@app.route('/')
def index():
    """Render the main page"""
    return render_template('index.html')

def upload_single_file(file_path, file_content, mime_type, api_key, folder_id, session_id):
    """Upload a single file to the Langdock API"""
    try:
        print(f"Processing file: {file_path}")
        
        # Make the API request with retry logic
        max_retries = 2
        retry_count = 0
        
        while retry_count <= max_retries:
            try:
                # Add a small delay if this is a retry to help with rate limiting
                if retry_count > 0:
                    retry_delay = 1 + retry_count * 2  # Exponential backoff
                    print(f"Retry {retry_count} for {file_path}, waiting {retry_delay}s")
                    time.sleep(retry_delay)
                
                # Create a fresh BytesIO object for each attempt
                files_data = {
                    'file': (os.path.basename(file_path), io.BytesIO(file_content), mime_type)
                }
                headers = {'Authorization': f'Bearer {api_key}'}
                
                response = requests.post(
                    f'https://api.langdock.com/knowledge/{folder_id}',
                    files=files_data,
                    headers=headers,
                    timeout=30  # Set a reasonable timeout
                )
                
                # Check response
                if response.status_code == 200 or response.status_code == 201:
                    print(f"Successfully uploaded: {file_path}")
                    
                    # Update progress
                    if session_id in active_uploads:
                        active_uploads[session_id]['uploaded'] += 1
                        active_uploads[session_id]['last_update'] = time.time()
                        
                        # Send progress update
                        send_progress_update(session_id)
                    
                    return {
                        'file': file_path,
                        'status': 'success',
                        'message': 'Successfully uploaded'
                    }
                elif response.status_code >= 500:
                    # Server error, we should retry
                    print(f"Server error ({response.status_code}) for {file_path}: {response.text}")
                    retry_count += 1
                    if retry_count > max_retries:
                        return {
                            'file': file_path,
                            'status': 'error',
                            'message': f"Failed after {max_retries} retries: {response.text}"
                        }
                else:
                    # Client error, don't retry
                    error_message = f"Failed to upload: {response.text}"
                    print(f"{error_message}")
                    return {
                        'file': file_path,
                        'status': 'error',
                        'message': error_message
                    }
            except requests.exceptions.RequestException as e:
                print(f"API request error for {file_path}: {str(e)}")
                retry_count += 1
                if retry_count > max_retries:
                    return {
                        'file': file_path,
                        'status': 'error',
                        'message': f'API request error after {max_retries} retries: {str(e)}'
                    }
    except Exception as e:
        print(f"Error processing file: {file_path} - {str(e)}")
        return {
            'file': file_path,
            'status': 'error',
            'message': f'Error processing file: {str(e)}'
        }

def send_progress_update(session_id):
    """Send a progress update to the client"""
    if session_id not in active_uploads:
        return
        
    if session_id in event_queues:
        upload_data = active_uploads[session_id]
        event_queues[session_id].put({
            'type': 'progress',
            'total': upload_data['total'],
            'uploaded': upload_data['uploaded'],
            'percent': int((upload_data['uploaded'] / upload_data['total']) * 100) if upload_data['total'] > 0 else 0
        })

@app.route('/progress')
def progress():
    """Stream the upload progress using server-sent events"""
    session_id = request.args.get('session_id')
    
    # Create a new queue for this session if it doesn't exist
    if session_id not in event_queues:
        event_queues[session_id] = Queue()
    
    def generate():
        # Send initial progress
        if session_id in active_uploads:
            upload_data = active_uploads[session_id]
            yield f"data: {json.dumps({'type': 'progress', 'total': upload_data['total'], 'uploaded': upload_data['uploaded'], 'percent': int((upload_data['uploaded'] / upload_data['total']) * 100) if upload_data['total'] > 0 else 0})}\n\n"
        
        try:
            while True:
                # Check if session is completed
                if session_id in active_uploads:
                    upload_data = active_uploads[session_id]
                    is_completed = upload_data.get('completed', False)
                    
                    if is_completed:
                        yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                        break
                
                # Check if we have a new event in the queue
                try:
                    # Poll the queue with a timeout to avoid blocking forever
                    event_data = event_queues[session_id].get(timeout=0.5)
                    yield f"data: {json.dumps(event_data)}\n\n"
                except Exception:
                    # No event available, send a heartbeat to keep the connection alive
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                
                # Check if the session no longer exists or has timed out
                if session_id not in active_uploads:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Session not found'})}\n\n"
                    break
                    
                # Check for timeout (no updates in 60 seconds)
                if time.time() - active_uploads[session_id].get('last_update', active_uploads[session_id]['start_time']) > 60:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Upload timed out'})}\n\n"
                    break
        except GeneratorExit:
            # Clean up when the client disconnects
            print(f"Client disconnected from SSE stream for session {session_id}")
    
    return Response(generate(), mimetype='text/event-stream')

@app.route('/upload', methods=['POST'])
def upload():
    """Handle folder uploads from the web interface"""
    try:
        # Get session ID from the request (sent by browser)
        session_id = request.form.get('session_id')
        if not session_id:
            session_id = f"session_{int(time.time() * 1000)}_{str(uuid.uuid4())[:10]}"
        
        # Get API key and folder ID from form
        api_key = request.form.get('api_key')
        folder_id = request.form.get('folder_id')
        
        # Validate API key and folder ID
        if not api_key or not folder_id:
            return jsonify({'error': 'API key and folder ID are required'}), 400
        
        # Check if files were uploaded
        if 'files[]' not in request.files:
            return jsonify({'error': 'No files part in the request'}), 400
        
        files = request.files.getlist('files[]')
        paths = request.form.getlist('paths[]')
        
        if not files or files[0].filename == '':
            return jsonify({'error': 'No files selected'}), 400
        
        print(f"Received {len(files)} files for upload with session ID: {session_id}")
        print(f"Using folder ID: {folder_id}")
        
        # Initialize session data
        active_uploads[session_id] = {
            'total': len(files),
            'uploaded': 0,
            'completed': False,
            'start_time': time.time(),
            'last_update': time.time()
        }
        
        # Create event queue for this session
        if session_id not in event_queues:
            event_queues[session_id] = Queue()
        
        # Pre-process all files - read their content before the thread starts
        file_data = []
        for file, path in zip(files, paths):
            try:
                # Read the file content and determine MIME type
                content = file.read()
                mime_type, _ = mimetypes.guess_type(path)
                if not mime_type:
                    mime_type = 'application/octet-stream'
                
                file_data.append((path, content, mime_type))
            except Exception as e:
                print(f"Error preprocessing file {path}: {str(e)}")
                # Add an error entry for this file
                file_data.append((path, None, None))
        
        # Create thread-safe results list
        results_list = []
        
        def process_uploads():
            nonlocal results_list
            
            try:
                # Use thread pool for parallel uploads, but with controlled concurrency
                # Increase max_workers to 3 for better performance while still being careful with API limits
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                    futures = []
                    future_to_path = {}
                    
                    # Submit all uploads
                    for data in file_data:
                        if data[1] is None:  # Skip files that failed preprocessing
                            results_list.append({
                                'file': data[0],
                                'status': 'error',
                                'message': 'Error preprocessing file'
                            })
                            continue
                        
                        path, content, mime = data
                        future = executor.submit(
                            upload_single_file,
                            path,
                            content,
                            mime,
                            api_key,
                            folder_id,
                            session_id
                        )
                        futures.append(future)
                        future_to_path[future] = path
                    
                    # Process results as they complete (this automatically handles concurrency)
                    for future in concurrent.futures.as_completed(futures):
                        file_path = future_to_path[future]
                        try:
                            result = future.result()
                            results_list.append(result)
                            print(f"Completed: {file_path}")
                        except Exception as e:
                            print(f"Error processing {file_path}: {str(e)}")
                            results_list.append({
                                'file': file_path,
                                'status': 'error',
                                'message': f'Error: {str(e)}'
                            })
                
                # Mark as completed and store results
                if session_id in active_uploads:
                    active_uploads[session_id]['completed'] = True
                    active_uploads[session_id]['results'] = results_list
                    
                    # Send completion event
                    if session_id in event_queues:
                        event_queues[session_id].put({'type': 'complete'})
                    
                    # Schedule cleanup
                    cleanup_after_delay(session_id)
            except Exception as e:
                print(f"Error in process_uploads: {str(e)}")
        
        # Start processing in a separate thread
        upload_thread = threading.Thread(target=process_uploads)
        upload_thread.daemon = True
        upload_thread.start()
        
        # Return a success response immediately
        return jsonify({
            'status': 'processing',
            'message': 'Upload started successfully',
            'session_id': session_id
        })
    
    except Exception as e:
        print(f"Upload error: {str(e)}")
        return jsonify({'error': f'An error occurred during upload: {str(e)}'}), 500

def cleanup_after_delay(session_id, delay=60):
    """Clean up session data after a delay"""
    def cleanup():
        time.sleep(delay)
        if session_id in active_uploads:
            del active_uploads[session_id]
        if session_id in event_queues:
            del event_queues[session_id]
    
    threading.Thread(target=cleanup).start()

@app.route('/status', methods=['GET'])
def check_status():
    """Check the status of an upload session"""
    session_id = request.args.get('session_id')
    
    if not session_id or session_id not in active_uploads:
        return jsonify({'status': 'error', 'message': 'Invalid session ID'}), 400
        
    session_data = active_uploads[session_id]
    
    # If the upload is complete, return the results
    if session_data.get('completed', False):
        results = session_data.get('results', [])
        
        # Count successes and failures
        success_count = sum(1 for r in results if r.get('status') == 'success')
        error_count = sum(1 for r in results if r.get('status') == 'error')
        
        total_time = time.time() - session_data['start_time']
        
        return jsonify({
            'status': 'complete',
            'results': results,
            'summary': {
                'total': len(results),
                'success': success_count,
                'error': error_count,
                'time_taken': round(total_time, 2)
            }
        })
    
    # Otherwise, return the current progress
    return jsonify({
        'status': 'processing',
        'progress': {
            'total': session_data['total'],
            'uploaded': session_data['uploaded'],
            'percent': round((session_data['uploaded'] / session_data['total']) * 100) if session_data['total'] > 0 else 0
        }
    })

if __name__ == '__main__':
    app.run(debug=os.environ.get('DEBUG', False), port=5001)
