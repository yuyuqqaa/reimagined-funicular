from flask import Flask, request, Response, stream_with_context
import requests
from urllib.parse import urlparse, quote, unquote
import re

ENABLE_MODIFICATION = True  # 修改开关：True启用修改，False禁用修改

app = Flask(__name__)

def safe_decode(content, default_encoding='utf-8'):
    """安全解码内容，默认使用UTF-8"""
    if not content:
        return "", default_encoding
        
    try:
        # 优先尝试UTF-8
        try:
            return content.decode('utf-8'), 'utf-8'
        except UnicodeDecodeError:
            pass
        
        # 尝试常见中文编码
        for encoding in ['gbk', 'gb2312', 'gb18030', 'big5']:
            try:
                return content.decode(encoding), encoding
            except (UnicodeDecodeError, LookupError):
                continue
        
        # 最终回退到UTF-8，使用replace处理错误字符
        return content.decode('utf-8', errors='replace'), 'utf-8'
        
    except Exception:
        # 终极回退方案
        try:
            return content.decode('utf-8', errors='replace'), 'utf-8'
        except:
            return "", 'utf-8'

def safe_encode(text, encoding='utf-8'):
    """安全编码文本，默认使用UTF-8"""
    if not text:
        return b""
        
    try:
        return text.encode(encoding, errors='replace')
    except Exception:
        # 强制使用UTF-8
        return text.encode('utf-8', errors='replace')

def normalize_chinese_url(url):
    """规范化包含中文的URL"""
    try:
        parsed = urlparse(url)
        
        # 处理路径中的中文
        path_parts = parsed.path.split('/')
        normalized_path = '/'.join(quote(unquote(part), safe='') for part in path_parts)
        
        # 处理查询参数中的中文
        if parsed.query:
            query_parts = []
            for param in parsed.query.split('&'):
                if '=' in param:
                    key, value = param.split('=', 1)
                    key = quote(unquote(key), safe='')
                    value = quote(unquote(value), safe='')
                    query_parts.append(f"{key}={value}")
                else:
                    query_parts.append(quote(unquote(param), safe=''))
            normalized_query = '&'.join(query_parts)
        else:
            normalized_query = ''
        
        # 重建URL
        normalized_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            normalized_path,
            parsed.params,
            normalized_query,
            parsed.fragment
        ))
        
        return normalized_url
    except Exception:
        return url

def detect_protocol(domain):
    """检测域名支持的协议（HTTP/HTTPS）"""
    # 先规范化域名中的中文
    normalized_domain = normalize_chinese_url(domain)
    domain = normalized_domain.split('://')[-1] if '://' in normalized_domain else normalized_domain
    
    # 先尝试HTTPS
    https_url = f"https://{domain}"
    try:
        response = requests.head(https_url, allow_redirects=False, timeout=10)
        if response.status_code < 400:
            return https_url
    except:
        pass
    
    # 回退到HTTP
    return f"http://{domain}"

def handle_html_rewrite(text, original_url):
    """处理HTML重写，修复相对链接"""
    try:
        mirror_base = f"{request.scheme}://{request.host}{request.path}"
        
        # 定义需要重写的标签和属性
        rewrite_rules = [
            (r'<(a)([^>]*href=["\'])(?!https?://|//|data:|javascript:|mailto:|tel:)([^"\']*)', 'href'),
            (r'<(img)([^>]*src=["\'])(?!https?://|//|data:|javascript:)([^"\']*)', 'src'),
            (r'<(link)([^>]*href=["\'])(?!https?://|//|data:|javascript:)([^"\']*)', 'href'),
            (r'<(script)([^>]*src=["\'])(?!https?://|//|data:|javascript:)([^"\']*)', 'src'),
            (r'<(form)([^>]*action=["\'])(?!https?://|//|data:|javascript:)([^"\']*)', 'action'),
            (r'<(iframe)([^>]*src=["\'])(?!https?://|//|data:|javascript:)([^"\']*)', 'src')
        ]
        
        modified_text = text
        
        for pattern, attr in rewrite_rules:
            def replace_callback(match):
                try:
                    tag_name = match.group(1)
                    attrs_before = match.group(2)
                    original_path = match.group(3)
                    
                    # 跳过特殊路径
                    if original_path.startswith(('#', 'javascript:', 'mailto:', 'tel:', 'data:')):
                        return match.group(0)
                    
                    # 处理绝对路径（以/开头）
                    if original_path.startswith('/'):
                        original_path = original_path[1:]
                    
                    # URL编码路径中的中文
                    try:
                        decoded_path = unquote(original_path)
                        encoded_path = quote(decoded_path, safe='/@:+?=&%#')
                    except:
                        encoded_path = original_path
                    
                    new_url = f"{mirror_base}/{encoded_path}"
                    return f'<{tag_name}{attrs_before}{new_url}'
                
                except Exception:
                    return match.group(0)
            
            modified_text = re.sub(pattern, replace_callback, modified_text, flags=re.IGNORECASE)
        
        return modified_text
        
    except Exception as e:
        app.logger.error(f"HTML重写错误: {str(e)}")
        return text

def remove_restrictive_headers(headers):
    """移除限制性头信息"""
    headers_to_remove = [
        'content-security-policy',
        'Content-Security-Policy',
        'x-frame-options',
        'X-Frame-Options',
        'x-content-type-options',
        'X-Content-Type-Options'
    ]
    
    new_headers = {}
    for key, value in headers.items():
        if key.lower() not in [h.lower() for h in headers_to_remove]:
            new_headers[key] = value
    
    return new_headers

def fix_content_type(headers):
    """修复Content-Type头信息，强制使用UTF-8"""
    if not headers:
        return {}
        
    new_headers = dict(headers)
    
    content_type = new_headers.get('Content-Type', '') or new_headers.get('content-type', '')
    if not content_type:
        return new_headers
    
    if 'text/html' in content_type:
        if 'charset=' in content_type:
            # 更新编码声明为UTF-8
            new_headers['Content-Type'] = re.sub(
                r'charset=[^;]+', 
                'charset=utf-8', 
                content_type
            )
        else:
            # 添加UTF-8编码声明
            base_type = content_type.split(';')[0].strip()
            new_headers['Content-Type'] = f'{base_type}; charset=utf-8'
    
    return new_headers

@app.route('/', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
def root_handler():
    """根路径处理"""
    return "请输入 / 后面的链接", 400, {'Content-Type': 'text/html; charset=utf-8'}

@app.route('/<path:url_path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
def proxy_handler(url_path):
    """主要的代理处理函数"""
    try:
        # 处理中文URL路径解码
        try:
            decoded_url_path = unquote(url_path)
        except:
            decoded_url_path = url_path
        
        # 构建完整的查询字符串和路径
        query_string = f"?{request.query_string.decode('utf-8', errors='ignore')}" if request.query_string else ""
        target_url_str = decoded_url_path + query_string
        
        # 检查是否包含协议头
        has_protocol = target_url_str.startswith(('http://', 'https://'))
        
        if not has_protocol:
            actual_url_str = detect_protocol(target_url_str)
        else:
            actual_url_str = target_url_str
        
        # 规范化URL中的中文
        actual_url_str = normalize_chinese_url(actual_url_str)
        
        app.logger.info(f"代理请求: {actual_url_str}")
        
        # 准备请求头
        headers = {key: value for key, value in request.headers if key.lower() != 'host'}
        headers['User-Agent'] = 'Mozilla/5.0 (兼容代理服务器)'
        
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
        
        # 处理HTML重写
        if ENABLE_MODIFICATION and 'text/html' in response.headers.get('content-type', '').lower():
            # 获取原始内容字节
            content_bytes = response.content
            
            # 安全解码内容（优先UTF-8）
            decoded_content, detected_encoding = safe_decode(content_bytes)
            
            # 重写HTML内容
            modified_content = handle_html_rewrite(decoded_content, request.url)
            
            # 重新编码为UTF-8
            encoded_content = safe_encode(modified_content, 'utf-8')
            
            # 移除限制性头信息并修复Content-Type
            response_headers = remove_restrictive_headers(response.headers)
            response_headers = fix_content_type(response_headers)
            
            # 确保有正确的Content-Type
            if 'Content-Type' not in response_headers and 'content-type' not in response_headers:
                response_headers['Content-Type'] = 'text/html; charset=utf-8'
            
            return Response(
                encoded_content,
                status=response.status_code,
                headers=response_headers
            )
        
        # 对于非HTML内容，流式传输
        def generate():
            for chunk in response.iter_content(chunk_size=8192):
                yield chunk
        
        # 处理非HTML内容的编码头信息
        response_headers = remove_restrictive_headers(response.headers)
        content_type = response_headers.get('Content-Type', '') or response_headers.get('content-type', '')
        
        if content_type and 'text/' in content_type and 'charset=' not in content_type:
            # 为文本内容添加UTF-8编码声明
            base_type = content_type.split(';')[0].strip()
            response_headers['Content-Type'] = f'{base_type}; charset=utf-8'
        
        return Response(
            stream_with_context(generate()),
            status=response.status_code,
            headers=response_headers
        )
        
    except requests.exceptions.Timeout:
        return "请求超时", 504, {'Content-Type': 'text/html; charset=utf-8'}
    except requests.exceptions.RequestException as e:
        return f"请求失败: {str(e)}", 500, {'Content-Type': 'text/html; charset=utf-8'}
    except Exception as e:
        app.logger.error(f"服务器错误: {str(e)}")
        return f"服务器错误: {str(e)}", 500, {'Content-Type': 'text/html; charset=utf-8'}

@app.after_request
def add_cors_headers(response):
    """添加CORS头信息，支持跨域访问"""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, PATCH, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    
    # 确保响应有正确的UTF-8编码头
    if 'Content-Type' in response.headers and 'text/' in response.headers['Content-Type']:
        if 'charset=' not in response.headers['Content-Type']:
            response.headers['Content-Type'] = response.headers['Content-Type'] + '; charset=utf-8'
    
    return response

# 简化的HTML重写版本（可选）
def simple_html_rewrite(text, base_url):
    """简化的HTML重写，只处理最基本的标签"""
    mirror_base = f"{request.scheme}://{request.host}{request.path}"
    
    # 简单的替换规则
    replacements = [
        (r'href="/([^"]*)"', f'href="{mirror_base}/\\1"'),
        (r'src="/([^"]*)"', f'src="{mirror_base}/\\1"'),
        (r"href='/([^']*)'", f"href='{mirror_base}/\\1'"),
        (r"src='/([^']*)'", f"src='{mirror_base}/\\1'"),
    ]
    
    modified_text = text
    for pattern, replacement in replacements:
        modified_text = re.sub(pattern, replacement, modified_text)
    
    return modified_text

if __name__ == '__main__':
    # 设置UTF-8环境
    import os
    import sys
    import io
    
    # 设置标准输出的编码为UTF-8
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    
    app.run(host='0.0.0.0', port=5000, debug=True)
