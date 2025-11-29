from flask import Flask, request, Response, jsonify, render_template
import requests
from urllib.parse import urljoin, urlparse
import re
import subprocess
import shlex
import socket # 引入 socket 用于 IP 验证

app = Flask(__name__)

# 修改开关：True启用修改，False禁用修改
ENABLE_MODIFICATION = True
# M3U8代理前缀
M3U8_PROXY_PREFIX = "[[[m3u8_host]]]"


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def proxy(path):
    url = request.url
    
    if not path:
        return "请输入 / 后面的链接", 400
    
    # 构建目标URL
    target_url_str = path + ('?' + request.query_string.decode() if request.query_string else '')
    
    # 检查是否包含协议
    has_protocol = target_url_str.startswith(('http://', 'https://'))
    
    if not has_protocol:
        actual_url_str = detect_protocol(target_url_str)
    else:
        actual_url_str = target_url_str
    
    try:
        # 如果是M3U8文件，修改请求URL
        if is_m3u8_file(actual_url_str):
            # 在原始URL前加上代理前缀
            proxied_url = M3U8_PROXY_PREFIX + actual_url_str
            print(f"M3U8代理: {actual_url_str} -> {proxied_url}")
            actual_url_str = proxied_url
        
        # 创建请求到目标网站
        headers = {key: value for key, value in request.headers if key.lower() != 'host'}
        
        resp = requests.request(
            method=request.method,
            url=actual_url_str,
            headers=headers,
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=True,
            stream=True
        )
        
        content_type = resp.headers.get('content-type', '').lower()
        
        # 当修改开关开启且是HTML内容时进行DOM重写
        if ENABLE_MODIFICATION and 'text/html' in content_type:
            return handle_html_rewrite(resp, url)
        
        # 返回原始响应
        response_headers = [(name, value) for name, value in resp.headers.items()]
        return Response(resp.content, status=resp.status_code, headers=response_headers)
        
    except Exception as error:
        return f"请求失败: {str(error)}", 500

def is_m3u8_file(url):
    """检查是否为M3U8文件"""
    url_lower = url.lower()
    
    # 通过URL后缀判断
    if url_lower.endswith(('.m3u8', '.m3u')):
        return True
    
    # 通过URL路径中包含m3u8关键字判断（有些URL可能没有后缀）
    if '/m3u8/' in url_lower or '.m3u8?' in url_lower or 'format=m3u8' in url_lower:
        return True
    
    return False

def handle_html_rewrite(response, original_url):
    """处理HTML重写，修改相对链接"""
    text = response.text
    
   
    host = "[[[host]]]"
    mirror_base = f"{request.scheme}://{host}{request.path}"
    
    # 替换相对链接为绝对链接
    def replace_relative_links(match):
        prefix = match.group(1)
        path = match.group(2)
        # 如果路径已经是绝对路径或包含协议，则不替换
        if path.startswith(('http://', 'https://', '//')):
            return match.group(0)
        # 确保路径不以斜杠开头
        if path.startswith('/'):
            path = path[1:]
        return f'{prefix}{mirror_base}/{path}'
    
    # 使用正则表达式替换链接
    modified_text = re.sub(
        r'(<a[^>]+href=["\'])(?!https?://)([^"\']+)',
        replace_relative_links,
        text,
        flags=re.IGNORECASE
    )
    
    modified_text = re.sub(
        r'(<img[^>]+src=["\'])(?!https?://)([^"\']+)',
        replace_relative_links,
        modified_text,
        flags=re.IGNORECASE
    )
    
    # 移除可能阻止资源加载的安全策略头
    headers = dict(response.headers)
    headers_to_remove = ['content-security-policy', 'Content-Security-Policy']
    for header in headers_to_remove:
        if header in headers:
            del headers[header]
    
    return Response(modified_text, status=response.status_code, headers=headers)

def detect_protocol(domain):
    """检测使用HTTP还是HTTPS协议"""
    try:
        https_url = f"https://{domain}"
        response = requests.head(https_url, allow_redirects=False, timeout=5)
        if response.status_code < 400:
            return https_url
    except:
        pass
    return f"http://{domain}"



# --- 后端函数 (与之前相同) ---

def is_valid_domain(domain):
    """验证域名格式"""
    if len(domain) > 255:
        return False
    if domain[-1] == ".":
        domain = domain[:-1]
    allowed = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$", re.IGNORECASE)
    return allowed.match(domain) is not None

def is_valid_ip(ip):
    """验证IP地址格式"""
    try:
        # 尝试 IPv4
        socket.inet_pton(socket.AF_INET, ip)
        return True
    except socket.error:
        try:
            # 尝试 IPv6
            socket.inet_pton(socket.AF_INET6, ip)
            return True
        except socket.error:
            return False

def safe_tcping(host, port=80, timeout=5):
    """
    使用 tcping 命令进行安全的TCP连接测试，测试3次
    返回: (success, output, error_message)
    """
    if not host or not isinstance(host, str):
        return False, "", "无效的主机名"
    
    # 确保 port 和 timeout 是整数
    try:
        port = int(port)
        timeout = int(timeout)
    except ValueError:
        return False, "", "端口号或超时时间必须是有效的整数"

    if port < 1 or port > 65535:
        return False, "", "端口号必须在1-65535之间"
    
    if timeout < 1 or timeout > 30:
        return False, "", "超时时间必须在1-30秒之间"
    
    host = host.strip().lower()
    
    if not (is_valid_domain(host) or is_valid_ip(host)):
        return False, "", "无效的域名或IP地址格式"
    
    try:
        cmd = [
            'tcping',
            '-c', '3',
            '-t', str(timeout),
            host,
            str(port)
        ]
        
        safe_cmd = shlex.split(' '.join(cmd))
        
        # 核心：执行命令并捕获原始输出 (包括颜色码)
        result = subprocess.run(
            safe_cmd,
            capture_output=True,
            text=True,
            timeout=timeout * 3 + 5
        )
        
        full_output = f"命令: {' '.join(cmd)}\n\n"
        full_output += "=" * 50 + "\n"
        full_output += "标准输出:\n"
        full_output += result.stdout + "\n"
        full_output += "=" * 50 + "\n"
        full_output += "错误输出:\n"
        full_output += result.stderr
        
        # 判断是否成功（检查 returncode 和标准输出）
        success = (result.returncode == 0 and result.stdout.strip() != "")
        
        return success, full_output, result.stderr if not success else ""
            
    except subprocess.TimeoutExpired:
        error_msg = f"命令执行超时 (总超时: {timeout * 3 + 5}秒)"
        return False, error_msg, error_msg
    except FileNotFoundError:
        error_msg = "tcping 命令未找到，请确保已安装。"
        return False, error_msg, error_msg
    except Exception as e:
        error_msg = f"执行错误: {str(e)}"
        return False, error_msg, error_msg

# --- 路由 ---

@app.route('/tcping/', methods=['GET'])
def index():
    """主页 - 使用 templates/index.html 文件渲染"""
    return render_template('index.html')

@app.route('/tcping/', methods=['POST'])
def tcping_api():
    """TCPing API接口 - 使用 JSON 请求体"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': '无效的JSON数据',
                'output': '',
                'host': '', 'port': 0
            }), 400
        
        host = data.get('host', '').strip()
        port = data.get('port', 80)
        timeout = data.get('timeout', 5)
        
        if not host:
            return jsonify({
                'success': False,
                'error': '主机名不能为空',
                'output': '',
                'host': host, 'port': port
            }), 400
        
        success, output, error = safe_tcping(host, port, timeout)
        
        return jsonify({
            'success': success,
            'host': host,
            'port': port,
            'output': output,
            'error': error
        })
            
    except Exception as e:
        req_data = request.get_json(silent=True) or {}
        return jsonify({
            'success': False,
            'error': f'服务器错误: {str(e)}',
            'output': '',
            'host': req_data.get('host', ''),
            'port': req_data.get('port', 0)
        }), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
