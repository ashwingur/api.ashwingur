from flask_login import login_required
from app.filetools import bp
from flask import Flask, request, send_file, jsonify
from PIL import Image
from moviepy.editor import VideoFileClip
import io
from app.extensions import limiter, login_manager, roles_required
import sys
import zipfile
import os

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
        if file.content_type.startswith('image/'):
            img = Image.open(file.stream)

            # Convert images with alpha channel to RGB before saving as JPG or PDF
            if format in ('jpeg', 'pdf') and img.mode in ('RGBA', 'LA'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                background.paste(img, (0, 0), img if img.mode == 'RGBA' else img.convert('RGBA'))
                img = background

            byte_io = io.BytesIO()
            if format == 'pdf':
                img.save(byte_io, format='PDF')
            else:
                img.save(byte_io, format=format)
            byte_io.seek(0)
            converted_files.append((file.filename, byte_io))
        elif file.content_type in ['video/mp4', 'video/x-matroska']:
            byte_io = io.BytesIO()
            temp_input = io.BytesIO(file.read())
            temp_input.seek(0)

            # Create a temporary file for moviepy to read from
            temp_input_file = f"/tmp/input_{file.filename}"
            with open(temp_input_file, 'wb') as f:
                f.write(temp_input.getbuffer())

            clip = VideoFileClip(temp_input_file)

            temp_output_file = f"/tmp/output_{file.filename}.{format}"
            if format in ['mp4', 'mkv']:
                codec = 'libx264' if format == 'mp4' else 'libvpx-vp9'
                clip.write_videofile(temp_output_file, codec=codec, audio_codec='aac')

            with open(temp_output_file, 'rb') as f:
                byte_io.write(f.read())

            byte_io.seek(0)
            converted_files.append((file.filename, byte_io))

            # Clean up temporary files
            os.remove(temp_input_file)
            os.remove(temp_output_file)
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
