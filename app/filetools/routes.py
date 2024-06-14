from flask_login import login_required
from app.filetools import bp
from flask import request, send_file, jsonify
from PIL import Image
import io
from app.extensions import limiter, login_manager, roles_required
import sys
import zipfile
import os
import tempfile

@bp.route('/convert', methods=['POST'])
@login_required
@roles_required('admin', 'user')
def convert_files():
    files = request.files.getlist('files')
    format = request.form.get('format').lower()

    # Convert 'jpg' to 'jpeg' as PIL expects 'jpeg'
    if format == 'jpg':
        format = 'jpeg'

    print(f"request received: files: {files}, format: {format}", file=sys.stderr)

    converted_files = []

    for file in files:
        if file.filename.lower().endswith('.eps') or file.content_type.startswith('image/'):
            # Create a temporary file to handle EPS content
            with tempfile.NamedTemporaryFile(suffix=".eps") as temp_eps_file:
                temp_eps_file.write(file.read())
                temp_eps_file.flush()
                img = Image.open(temp_eps_file.name)

                # If the file is an EPS, Pillow uses Ghostscript to process it
                if file.filename.lower().endswith('.eps'):
                    img.load(scale=5)  # Increase resolution for better quality
                    img = img.convert('RGB')  # Convert to RGB mode

                byte_io = io.BytesIO()
                if format == 'pdf':
                    # Convert image to PDF
                    img.save(byte_io, format='PDF')
                else:
                    img.save(byte_io, format=format)
                byte_io.seek(0)
                converted_files.append((file.filename, byte_io))
        else:
            # Handle other file types
            byte_io = io.BytesIO(file.read())
            byte_io.seek(0)
            converted_files.append((file.filename, byte_io))

    if len(converted_files) == 1:
        return send_file(converted_files[0][1], as_attachment=True, download_name=f'{os.path.splitext(converted_files[0][0])[0]}.{format}')
    
    # Handle multiple files by zipping them
    zip_io = io.BytesIO()
    with zipfile.ZipFile(zip_io, 'w') as zip_file:
        for file_name, byte_io in converted_files:
            converted_name = f"{os.path.splitext(file_name)[0]}.{format}"
            zip_file.writestr(converted_name, byte_io.getvalue())

    zip_io.seek(0)
    return send_file(zip_io, as_attachment=True, download_name='converted_files.zip', mimetype='application/zip')
