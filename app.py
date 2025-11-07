from flask import Flask, request, Response, stream_with_context
import requests
from urllib.parse import urlparse, urljoin
import re
from functools import wraps

# ==================== 配置区域 ====================
ENABLE_MODIFICATION = True  # 修改开关：True启用修改，False禁用修改

# 主机名配置（根据你的实际情况修改）
PROXY_HOST = "uscf.996855.xyz"  # 你的代理域名或IP
PROXY_PORT = ""  # 你的代理端口，如果是80或443可以留空
PROXY_SCHEME = "https"  # 你的代理协议：http 或 https

# 自动构建代理基础URL
if PROXY_PORT and PROXY_PORT not in ["80", "443"]:
    PROXY_BASE_URL = f"{PROXY_SCHEME}://{PROXY_HOST}:{PROXY_PORT}"
else:
    PROXY_BASE_URL = f"{PROXY_SCHEME}://{PROXY_HOST}"
# ==================== 配置结束 ====================

app = Flask(__name__)

def get_proxy_base_url():
    """获取代理基础URL"""
    return PROXY_BASE_URL

def detect_protocol(domain):
    """检测域名支持的协议（HTTP/HTTPS）"""
    # 先尝试HTTPS
    https_url = f"https://{domain}"
    try:
        response = requests.head(https_url, allow_redirects=False, timeout=5)
        if response.status_code < 400:
            return https_url
    except:
        pass
    
    # 回退到HTTP
    return f"http://{domain}"

def fix_encoding(text, response_encoding=None):
    """修复编码问题，确保文本正确解码"""
    if isinstance(text, bytes):
        # 如果是字节流，尝试多种编码方式解码
        encodings = ['utf-8', 'gbk', 'gb2312', 'iso-8859-1']
        
        if response_encoding and response_encoding.lower() in ['utf-8', 'gbk', 'gb2312']:
            encodings.insert(0, response_encoding)
        
        for encoding in encodings:
            try:
                return text.decode(encoding)
            except UnicodeDecodeError:
                continue
        
        # 如果所有编码都失败，使用 UTF-8 并忽略错误
        return text.decode('utf-8', errors='ignore')
    
    return text

def handle_m3u8_rewrite(content, base_url, original_url):
    """专门处理 m3u8 文件的重写"""
    if not content or not content.strip():
        return content or ""
    
    # 确保内容是字符串
    if isinstance(content, bytes):
        content = content.decode('utf-8', errors='ignore')
    
    lines = content.split('\n')
    rewritten_lines = []
    
    # 使用配置的代理基础URL
    proxy_base = get_proxy_base_url()
    
    for line in lines:
        line = line.strip()
        
        # 跳过空行（但保留空行以维持m3u8格式）
        if not line:
            rewritten_lines.append("")
            continue
            
        # 保留注释行
        if line.startswith('#'):
            rewritten_lines.append(line)
            continue
            
        # 处理TS文件路径和其他媒体文件
        if any(ext in line for ext in ['.ts', '.m3u8', '.m3u', '.mp4', '.m4s', '.aac', '.webm']):
            # 如果是绝对路径
            if line.startswith(('http://', 'https://')):
                # 已经是完整URL，直接重写为代理URL
                ts_url = line
                # 提取路径部分用于构建代理URL
                parsed_ts = urlparse(ts_url)
                # 构建代理URL：proxy_base/目标域名/路径
                proxy_ts_url = f"{proxy_base}/{parsed_ts.netloc}{parsed_ts.path}"
                if parsed_ts.query:
                    proxy_ts_url += f"?{parsed_ts.query}"
                rewritten_lines.append(proxy_ts_url)
                
            # 如果是相对路径
            else:
                # 构建完整的URL
                try:
                    if base_url and base_url.endswith('.m3u8'):
                        # 如果base_url是m3u8文件，使用其目录作为基础
                        base_dir = base_url.rsplit('/', 1)[0] + '/' if '/' in base_url else base_url
                        full_ts_url = urljoin(base_dir, line)
                    else:
                        full_ts_url = urljoin(base_url, line)
                    
                    # 转换为代理URL
                    parsed_ts = urlparse(full_ts_url)
                    proxy_ts_url = f"{proxy_base}/{parsed_ts.netloc}{parsed_ts.path}"
                    if parsed_ts.query:
                        proxy_ts_url += f"?{parsed_ts.query}"
                    rewritten_lines.append(proxy_ts_url)
                except Exception as e:
                    # 如果URL处理失败，保持原样
                    rewritten_lines.append(line)
        else:
            # 非媒体文件路径，保持原样
            rewritten_lines.append(line)
    
    return '\n'.join(rewritten_lines)

def handle_html_rewrite(text, original_url, response_encoding=None):
    """处理HTML重写，修复相对链接和编码问题"""
    # 首先修复编码
    if isinstance(text, bytes):
        text = fix_encoding(text, response_encoding)
    
    # 使用配置的代理基础URL
    proxy_base = get_proxy_base_url()
    mirror_base = f"{proxy_base}{request.path}"
    
    # 替换相对链接
    def replace_relative_links(match):
        tag_type = match.group(1)  # 'a' 或 'img'
        prefix = match.group(2)    # 属性名和引号前的部分
        path = match.group(3)      # 相对路径
        
        # 如果路径已经是绝对路径或者是协议相对路径，则不处理
        if path.startswith(('http://', 'https://', '//', 'data:', 'javascript:')):
            return match.group(0)
        
        return f'<{tag_type} {prefix}"{mirror_base}/{path}"'
    
    # 使用更精确的正则表达式匹配a和img标签
    try:
        modified_text = re.sub(
            r'<(a|img)([^>]*(href|src)=["\'])(?!https?://|//|data:|javascript:)([^"\']+)',
            lambda m: f'<{m.group(1)}{m.group(2)}{mirror_base}/{m.group(4)}',
            text,
            flags=re.IGNORECASE
        )
    except UnicodeError:
        # 如果编码错误，返回原始文本
        modified_text = text
    
    return modified_text

def remove_restrictive_headers(headers):
    """移除限制性头信息"""
    headers_to_remove = [
        'content-security-policy',
        'Content-Security-Policy',
        'x-frame-options',
        'X-Frame-Options',
        'access-control-allow-origin'
    ]
    
    new_headers = {}
    for key, value in headers.items():
        if key.lower() not in [h.lower() for h in headers_to_remove]:
            new_headers[key] = value
    
    return new_headers

def get_response_encoding(response):
    """从响应中获取正确的编码"""
    # 从Content-Type头获取编码
    content_type = response.headers.get('content-type', '')
    if 'charset=' in content_type:
        charset = re.search(r'charset=([^\s;]+)', content_type)
        if charset:
            return charset.group(1).lower()
    
    # 从HTML meta标签获取编码
    if response.headers.get('content-type', '').startswith('text/html'):
        try:
            # 查找meta标签中的charset
            charset_match = re.search(r'<meta[^>]*charset=([^\s"\'>]+)', response.text[:4096], re.IGNORECASE)
            if charset_match:
                return charset_match.group(1).lower()
        except:
            pass
    
    # 使用响应对象的编码
    if hasattr(response, 'encoding') and response.encoding:
        return response.encoding.lower()
    
    return 'utf-8'  # 默认使用UTF-8

def is_m3u8_content(content_type, url):
    """判断是否为m3u8内容"""
    if content_type in ['application/vnd.apple.mpegurl', 'audio/mpegurl', 'application/x-mpegurl', 'application/mpegurl']:
        return True
    if url and (url.endswith('.m3u8') or '.m3u8?' in url):
        return True
    return False

@app.route('/', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
def root_handler():
    """根路径处理"""
    return "请输入 / 后面的链接", 400

@app.route('/<path:url_path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
def proxy_handler(url_path):
    """主要的代理处理函数"""
    
    # 构建完整的查询字符串和路径
    query_string = f"?{request.query_string.decode()}" if request.query_string else ""
    target_url_str = url_path + query_string
    
    # 检查是否包含协议头
    has_protocol = target_url_str.startswith(('http://', 'https://'))
    
    if not has_protocol:
        actual_url_str = detect_protocol(target_url_str)
    else:
        actual_url_str = target_url_str
    
    try:
        # 准备请求头
        headers = {key: value for key, value in request.headers if key.lower() != 'host'}
        
        # 添加必要的请求头
        headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        
        # 准备请求体
        data = request.get_data() if request.method in ['POST', 'PUT', 'PATCH'] else None
        
        # 发送请求
        response = requests.request(
            method=request.method,
            url=actual_url_str,
            headers=headers,
            data=data,
            stream=True,
            allow_redirects=True,
            cookies=request.cookies,
            timeout=30
        )
        
        # 检查响应状态
        if response.status_code != 200:
            return f"上游服务器返回错误: {response.status_code}", response.status_code
        
        # 获取内容类型
        content_type = response.headers.get('content-type', '').lower()
        
        # 处理m3u8文件
        if (ENABLE_MODIFICATION and is_m3u8_content(content_type, actual_url_str)):
            
            # 获取原始内容（字节形式）
            content_bytes = response.content
            
            # 如果内容为空，返回错误
            if not content_bytes:
                return "m3u8文件内容为空", 500
            
            # 尝试解码内容
            try:
                content_text = content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    content_text = content_bytes.decode('latin-1')
                except:
                    content_text = content_bytes.decode('utf-8', errors='ignore')
            
            # 重写m3u8中的TS文件路径
            modified_content = handle_m3u8_rewrite(content_text, actual_url_str, request.url)
            
            # 设置正确的Content-Type
            response_headers = remove_restrictive_headers(response.headers)
            response_headers['Content-Type'] = 'application/vnd.apple.mpegurl; charset=utf-8'
            response_headers['Access-Control-Allow-Origin'] = '*'
            response_headers['Access-Control-Allow-Headers'] = '*'
            response_headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, PATCH'
            
            # 确保内容不为空
            if not modified_content or len(modified_content.strip()) == 0:
                modified_content = content_text  # 回退到原始内容
            
            return Response(
                modified_content,
                status=response.status_code,
                headers=response_headers
            )
        
        # 处理HTML重写
        elif (ENABLE_MODIFICATION and 
              content_type.startswith('text/html')):
            
            # 使用正确的编码处理内容
            if hasattr(response, 'text'):
                content = response.text
            else:
                content = fix_encoding(response.content, get_response_encoding(response))
            
            # 重写HTML内容
            modified_content = handle_html_rewrite(content, request.url, get_response_encoding(response))
            
            # 移除限制性头信息
            response_headers = remove_restrictive_headers(response.headers)
            
            return Response(
                modified_content,
                status=response.status_code,
                headers=response_headers,
                content_type=f"text/html; charset=utf-8"
            )
        
        # 对于TS文件和其他媒体文件，直接流式传输
        elif url_path.endswith(('.ts', '.m4s', '.mp4', '.webm', '.aac')):
            def generate():
                for chunk in response.iter_content(chunk_size=8192):
                    yield chunk
            
            response_headers = remove_restrictive_headers(response.headers)
            # 添加CORS头以便跨域访问
            response_headers['Access-Control-Allow-Origin'] = '*'
            
            return Response(
                stream_with_context(generate()),
                status=response.status_code,
                headers=response_headers
            )
        
        # 对于非HTML内容，流式传输
        else:
            def generate():
                for chunk in response.iter_content(chunk_size=8192):
                    yield chunk
            
            response_headers = remove_restrictive_headers(response.headers)
            
            return Response(
                stream_with_context(generate()),
                status=response.status_code,
                headers=response_headers
            )
        
    except requests.exceptions.RequestException as e:
        return f"请求失败: {str(e)}", 500
    except Exception as e:
        return f"服务器错误: {str(e)}", 500

# 添加CORS支持
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', '*')
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, PATCH')
    return response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
