from flask import Flask, request, Response, stream_with_context
import requests
from urllib.parse import urlparse
import re
from functools import wraps

ENABLE_MODIFICATION = True  # 修改开关：True启用修改，False禁用修改

app = Flask(__name__)

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

def handle_html_rewrite(text, original_url, response_encoding=None):
    """处理HTML重写，修复相对链接和编码问题"""
    # 首先修复编码
    if isinstance(text, bytes):
        text = fix_encoding(text, response_encoding)
    
    mirror_base = f"{request.scheme}://{request.host}{request.path}"
    
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
        'X-Frame-Options'
    ]
    
    new_headers = {}
    for key, value in headers.items():
        if key not in headers_to_remove:
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
            cookies=request.cookies
        )
        
        # 获取正确的编码
        response_encoding = get_response_encoding(response)
        
        # 处理HTML重写
        if (ENABLE_MODIFICATION and 
            response.headers.get('content-type', '').startswith('text/html')):
            
            # 使用正确的编码处理内容
            if hasattr(response, 'text'):
                content = response.text
            else:
                # 如果response.text不可用，手动解码
                content = fix_encoding(response.content, response_encoding)
            
            # 重写HTML内容
            modified_content = handle_html_rewrite(content, request.url, response_encoding)
            
            # 移除限制性头信息
            response_headers = remove_restrictive_headers(response.headers)
            
            # 确保返回正确的编码
            return Response(
                modified_content,
                status=response.status_code,
                headers=response_headers,
                content_type=f"text/html; charset=utf-8"  # 强制使用UTF-8
            )
        
        # 对于非HTML内容，流式传输
        def generate():
            for chunk in response.iter_content(chunk_size=8192):
                yield chunk
        
        # 移除限制性头信息
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
