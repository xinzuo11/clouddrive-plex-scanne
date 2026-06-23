#!/usr/bin/env python3
"""
CloudDrive2 Webhook to Plex Scanner
- 每个CD路径独立对应Plex库路径
"""

import os
import json
import time
import logging
import requests
from pathlib import Path
from flask import Flask, request, jsonify, render_template
from xml.etree import ElementTree
import configparser
from datetime import datetime
import urllib.parse

log_dir = '/app/logs'
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(log_dir, 'scanner.log'), encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

class MemoryLogHandler(logging.Handler):
    def __init__(self, capacity=500):
        super().__init__()
        self.capacity = capacity
        self.logs = []
    def emit(self, record):
        log_entry = self.format(record)
        self.logs.append(log_entry)
        if len(self.logs) > self.capacity:
            self.logs = self.logs[-self.capacity:]

memory_handler = MemoryLogHandler(500)
memory_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(memory_handler)

app = Flask(__name__)

class ConfigManager:
    def __init__(self, config_file='config.ini'):
        self.config_file = config_file
        self.config = configparser.ConfigParser()
        self.load()
    def load(self):
        if os.path.exists(self.config_file):
            self.config.read(self.config_file, encoding='utf-8')
        else:
            self.config['plex'] = {'url': 'http://localhost:32400', 'token': ''}
            self.config['webhook'] = {'token': ''}
            self.config['mappings'] = {}
            self.save()
    def save(self):
        with open(self.config_file, 'w', encoding='utf-8') as f:
            self.config.write(f)
    def get_plex_config(self):
        return {
            'plex_url': self.config.get('plex', 'url', fallback='http://localhost:32400'),
            'plex_token': self.config.get('plex', 'token', fallback=''),
            'webhook_token': self.config.get('webhook', 'token', fallback='')
        }
    def set_plex_config(self, data):
        if 'plex' not in self.config: self.config['plex'] = {}
        self.config['plex']['url'] = data.get('plex_url', 'http://localhost:32400')
        self.config['plex']['token'] = data.get('plex_token', '')
        if 'webhook' not in self.config: self.config['webhook'] = {}
        self.config['webhook']['token'] = data.get('webhook_token', '')
        self.save()
        logger.info("Plex配置已更新")
    def get_mappings(self):
        mappings = {}
        if self.config.has_section('mappings'):
            for key, value in self.config.items('mappings'):
                try: mappings[key] = json.loads(value)
                except: pass
        return mappings
    def set_mappings(self, mappings):
        if 'mappings' in self.config: self.config.remove_section('mappings')
        self.config.add_section('mappings')
        for name, mapping in mappings.items():
            self.config['mappings'][name] = json.dumps(mapping, ensure_ascii=False)
        self.save()
        logger.info(f"映射配置已更新，共 {len(mappings)} 个映射")

config_manager = ConfigManager()

class Scanner:
    def __init__(self):
        self.reload()
    def reload(self):
        config = config_manager.get_plex_config()
        self.plex_url = config['plex_url']
        self.plex_token = config['plex_token']
        self.webhook_token = config['webhook_token']
        self.mappings = config_manager.get_mappings()
    def test_plex(self, url=None, token=None):
        url = url or self.plex_url
        token = token or self.plex_token
        headers = {'X-Plex-Token': token} if token else {}
        try:
            resp = requests.get(f"{url}/library/sections", headers=headers, timeout=10)
            if resp.status_code == 200:
                root = ElementTree.fromstring(resp.content)
                libs = []
                for d in root.findall('.//Directory'):
                    loc = d.find('.//Location')
                    libs.append({'key': d.get('key'), 'title': d.get('title'), 'type': d.get('type'), 'path': loc.get('path') if loc is not None else ''})
                return True, libs
            return False, f"HTTP {resp.status_code}"
        except Exception as e:
            return False, str(e)
    def get_library_path_from_plex(self, library_id):
        success, libraries = self.test_plex()
        if success:
            for lib in libraries:
                if lib['key'] == library_id:
                    return lib.get('path', '')
        return ''
    def match_mapping(self, file_path):
        file_path = file_path.replace('\\', '/').rstrip('/')
        for name, mapping in self.mappings.items():
            # 新格式：paths 是数组 [{cd_path, plex_path}, ...]
            paths = mapping.get('paths', [])
            lib_id = mapping.get('plex_library_id', '')
            if not paths:
                # 兼容旧格式
                old_path = mapping.get('clouddrive_path', '')
                old_plex = mapping.get('plex_library_path', '')
                if old_path:
                    paths = [{'cd_path': old_path, 'plex_path': old_plex}]
            for p in paths:
                cd = p.get('cd_path', '').replace('\\', '/').rstrip('/')
                if cd and file_path.startswith(cd):
                    return name, lib_id, cd, p.get('plex_path', '')
        return None, None, None, None
    def scan(self, file_path):
        self.reload()
        file_path = file_path.replace('\\', '/').rstrip('/')
        logger.info(f"开始处理: {file_path}")
        name, lib_id, matched_cd, plex_base = self.match_mapping(file_path)
        if not lib_id:
            logger.warning(f"未找到匹配映射: {file_path}")
            return False, f"未找到匹配映射: {file_path}"
        logger.info(f"匹配到: {name} -> Plex库{lib_id} (CD:{matched_cd})")
        if '.' in os.path.basename(file_path) and not file_path.endswith('/'):
            scan_dir = os.path.dirname(file_path)
        else:
            scan_dir = file_path
        try:
            if scan_dir == matched_cd or scan_dir == matched_cd + '/':
                rel = ''
            else:
                rel = os.path.relpath(scan_dir, matched_cd)
        except:
            rel = ''
        if not plex_base:
            plex_base = self.get_library_path_from_plex(lib_id)
            if not plex_base:
                return False, "无法获取Plex库路径"
        if rel and rel != '.':
            scan_path = os.path.join(plex_base, rel).replace('\\', '/')
        else:
            scan_path = plex_base
        logger.info(f"扫描路径: {scan_path}")
        headers = {'X-Plex-Token': self.plex_token} if self.plex_token else {}
        encoded = urllib.parse.quote(scan_path, safe='')
        url = f"{self.plex_url}/library/sections/{lib_id}/refresh?path={encoded}"
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                logger.info(f"✅ 扫描成功: {scan_path}")
                return True, f"成功触发扫描: {scan_path}"
            return False, f"HTTP {resp.status_code}"
        except Exception as e:
            return False, str(e)

scanner = Scanner()

@app.route('/')
def index(): return render_template('index.html')
@app.route('/health')
def health(): return jsonify({'status': 'ok'})
@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    if request.method == 'GET': return jsonify(config_manager.get_plex_config())
    config_manager.set_plex_config(request.json)
    return jsonify({'success': True})
@app.route('/api/test-plex', methods=['POST'])
def api_test_plex():
    data = request.json
    s, r = scanner.test_plex(data.get('plex_url'), data.get('plex_token'))
    return jsonify({'success': s, 'libraries': r, 'library_count': len(r)} if s else {'success': False, 'error': r})
@app.route('/api/libraries')
def api_libraries():
    s, r = scanner.test_plex()
    return jsonify({'success': s, 'libraries': r} if s else {'success': False, 'error': r})
@app.route('/api/mappings', methods=['GET', 'POST'])
def api_mappings():
    if request.method == 'GET': return jsonify({'mappings': config_manager.get_mappings()})
    config_manager.set_mappings(request.json.get('mappings', {}))
    return jsonify({'success': True})
@app.route('/api/test-scan', methods=['POST'])
def api_test_scan():
    path = request.json.get('path', '')
    if not path: return jsonify({'success': False, 'message': '请输入路径'})
    success, message = scanner.scan(path)
    return jsonify({'success': success, 'message': message})
@app.route('/api/logs')
def api_logs():
    logs = memory_handler.logs.copy()
    if len(logs) < 50:
        log_file = '/app/logs/scanner.log'
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    logs = [l.strip() for l in f.readlines()[-200:]]
            except: pass
    return jsonify({'logs': logs[-200:]})
@app.route('/api/logs/clear', methods=['POST'])
def api_clear_logs():
    memory_handler.logs = []
    log_file = '/app/logs/scanner.log'
    if os.path.exists(log_file): open(log_file, 'w').close()
    return jsonify({'success': True})
@app.route('/webhook/clouddrive', methods=['POST'])
def webhook():
    if scanner.webhook_token:
        token = request.headers.get('X-Webhook-Token') or request.headers.get('authorization') or request.args.get('token')
        if token and token.startswith('basic '): token = token.replace('basic ', '')
        if token != scanner.webhook_token: return jsonify({'error': '认证失败'}), 401
    try:
        data = request.json or request.form.to_dict()
        if not data: return jsonify({'success': False, 'message': '空数据'}), 400
        logger.info(f"收到Webhook: {json.dumps(data, ensure_ascii=False)[:500]}")
        if data.get('event_category') == 'file' and data.get('event_name') == 'notify':
            changes = data.get('data', [])
            if not changes: return jsonify({'success': False, 'message': '没有文件变更数据'})
            results = []
            for c in changes:
                action = c.get('action', '')
                src = c.get('source_file', '')
                dst = c.get('destination_file', '')
                is_dir_raw = c.get('is_dir', False)
                if isinstance(is_dir_raw, str): is_dir = is_dir_raw.lower() == 'true'
                elif isinstance(is_dir_raw, bool): is_dir = is_dir_raw
                else: is_dir = False
                logger.info(f"变更: action={action}, src={src}, dst={dst}, is_dir={is_dir}")
                if action == 'create': fp = src
                elif action == 'rename' and dst: fp = dst
                elif action == 'delete': logger.info(f"忽略删除: {src}"); continue
                else: continue
                if is_dir:
                    if action == 'rename' and fp:
                        logger.info(f"目录移动，触发扫描: {fp}")
                        s, m = scanner.scan(fp)
                        results.append({"file": fp, "success": s, "message": m})
                    else: logger.info(f"跳过目录: {fp}")
                    continue
                if fp:
                    s, m = scanner.scan(fp)
                    results.append({'file': fp, 'success': s, 'message': m})
            if results: return jsonify({'success': True, 'results': results, 'processed': len(results)})
            return jsonify({'success': True, 'message': '没有需要处理的文件'})
        else:
            fp = data.get('path') or data.get('file_path') or data.get('source_file', '')
            if fp:
                s, m = scanner.scan(fp)
                return jsonify({'success': s, 'message': m})
            return jsonify({'success': False, 'message': '无法提取文件路径'})
    except Exception as e:
        logger.error(f"异常: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    print("\n" + "="*60)
    print("  CloudDrive2 -> Plex 扫描器已启动")
    print("="*60 + "\n")
    app.run(host='0.0.0.0', port=5001, debug=False)