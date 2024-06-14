from app.filetools import bp
from flask import Flask, request, send_file, jsonify
from PIL import Image
import io
from app.extensions import limiter
import sys
import zipfile
import os

@bp.route('/convert', methods=['POST'])
def convert_files():
    files = request.files.getlist('files')
    format = request.form.get('format').lower()

    # Convert 'jpg' to 'jpeg' as PIL expects 'jpeg'
    if format == 'jpg':
        format = 'jpeg'

    print(f"request received: files: {files}, format: {format}", file=sys.stderr)

    converted_files = []

    for file in files:
        if file.content_type.startswith('image/'):
            img = Image.open(file.stream)

            # Convert images with alpha channel to RGB before saving as JPG
            if format == 'jpeg' and img.mode in ('RGBA', 'LA'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                background.paste(img, (0, 0), img if img.mode == 'RGBA' else img.convert('RGBA'))
                img = background

            byte_io = io.BytesIO()
            img.save(byte_io, format=format)
            byte_io.seek(0)
            converted_files.append((file.filename, byte_io))
        else:
            # Handle non-image files
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
