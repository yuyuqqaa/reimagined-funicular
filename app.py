from flask import Flask, request, Response, stream_with_context
import requests
from urllib.parse import urlparse, quote, unquote
import re
import chardet

ENABLE_MODIFICATION = True  # 修改开关：True启用修改，False禁用修改

app = Flask(__name__)

def detect_encoding(content):
    """自动检测内容编码"""
    try:
        result = chardet.detect(content)
        encoding = result['encoding'] if result['confidence'] > 0.7 else 'utf-8'
        return encoding.lower()
    except:
        return 'utf-8'

def safe_decode(content, default_encoding='utf-8'):
    """安全解码内容，处理编码问题"""
    try:
        # 先尝试检测编码
        detected_encoding = detect_encoding(content)
        
        # 常见编码优先级
        encodings_to_try = [
            detected_encoding,
            'utf-8',
            'gbk',
            'gb2312',
            'big5',
            'latin-1'
        ]
        
        for encoding in set(encodings_to_try):
            try:
                if encoding:
                    return content.decode(encoding), encoding
            except (UnicodeDecodeError, LookupError):
                continue
        
        # 如果所有编码都失败，使用替代策略
        return content.decode(default_encoding, errors='replace'), default_encoding
        
    except Exception as e:
        # 最终回退
        return content.decode(default_encoding, errors='replace'), default_encoding

def safe_encode(text, encoding='utf-8'):
    """安全编码文本"""
    try:
        return text.encode(encoding)
    except UnicodeEncodeError:
        # 处理编码错误，使用替代字符
        return text.encode(encoding, errors='replace')

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

def handle_html_rewrite(text, original_url, content_encoding='utf-8'):
    """处理HTML重写，修复相对链接，支持中文编码"""
    try:
        mirror_base = f"{request.scheme}://{request.host}{request.path}"
        
        # 定义需要重写的标签和属性
        rewrite_patterns = [
            (r'<(a)([^>]*href=["\'])(?!https?://|//|data:|javascript:|mailto:|tel:)([^"\']*)', 'href'),
            (r'<(img)([^>]*src=["\'])(?!https?://|//|data:|javascript:)([^"\']*)', 'src'),
            (r'<(link)([^>]*href=["\'])(?!https?://|//|data:|javascript:)([^"\']*)', 'href'),
            (r'<(script)([^>]*src=["\'])(?!https?://|//|data:|javascript:)([^"\']*)', 'src'),
            (r'<(form)([^>]*action=["\'])(?!https?://|//|data:|javascript:)([^"\']*)', 'action'),
            (r'<(iframe)([^>]*src=["\'])(?!https?://|//|data:|javascript:)([^"\']*)', 'src')
        ]
        
        modified_text = text
        
        for pattern, attr in rewrite_patterns:
            def replace_callback(match):
                try:
                    full_tag = match.group(0)
                    tag_name = match.group(1)
                    attrs_before = match.group(2)
                    original_path = match.group(3)
                    
                    # 跳过特殊路径
                    if original_path.startswith(('#', 'javascript:', 'mailto:', 'tel:', 'data:')):
                        return full_tag
                    
                    # 处理绝对路径（以/开头）
                    if original_path.startswith('/'):
                        original_path = original_path[1:]
                    
                    # URL编码路径中的中文
                    try:
                        # 先解码再编码，确保中文正确处理
                        decoded_path = unquote(original_path)
                        encoded_path = quote(decoded_path, safe='/@:+?=&%#')
                    except:
                        encoded_path = original_path
                    
                    new_url = f"{mirror_base}/{encoded_path}"
                    return f'<{tag_name}{attrs_before}{new_url}'
                
                except Exception as e:
                    # 如果替换出错，返回原始内容
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

def fix_content_type(headers, actual_encoding):
    """修复Content-Type头信息中的编码声明"""
    new_headers = dict(headers)
    
    content_type = new_headers.get('Content-Type', '') or new_headers.get('content-type', '')
    if 'text/html' in content_type and 'charset=' in content_type:
        # 更新编码声明
        new_headers['Content-Type'] = re.sub(
            r'charset=[^;]+', 
            f'charset={actual_encoding}', 
            content_type
        )
    elif 'text/html' in content_type:
        # 添加编码声明
        new_headers['Content-Type'] = f'{content_type.split(";")[0]}; charset={actual_encoding}'
    
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
        headers['User-Agent'] = 'Mozilla/5.0 (兼容代理服务器; 中文支持)'
        
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
            
            # 安全解码内容
            decoded_content, detected_encoding = safe_decode(content_bytes)
            
            # 重写HTML内容
            modified_content = handle_html_rewrite(decoded_content, request.url, detected_encoding)
            
            # 重新编码内容
            encoded_content = safe_encode(modified_content, detected_encoding)
            
            # 移除限制性头信息并修复Content-Type
            response_headers = remove_restrictive_headers(response.headers)
            response_headers = fix_content_type(response_headers, detected_encoding)
            
            # 确保有正确的Content-Type
            if 'Content-Type' not in response_headers and 'content-type' not in response_headers:
                response_headers['Content-Type'] = f'text/html; charset={detected_encoding}'
            
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
        
        if 'text/' in content_type and 'charset=' not in content_type:
            # 为文本内容添加UTF-8编码声明
            response_headers['Content-Type'] = f'{content_type.split(";")[0]}; charset=utf-8'
        
        return Response(
            stream_with_context(generate()),
            status=response.status_code,
            headers=response_headers
        )
        
    except requests.exceptions.Timeout:
        return "请求超时", 504
    except requests.exceptions.RequestException as e:
        return f"请求失败: {str(e)}", 500
    except UnicodeDecodeError as e:
        return f"编码处理错误: {str(e)}", 500
    except Exception as e:
        app.logger.error(f"服务器错误: {str(e)}")
        return f"服务器错误: {str(e)}", 500

@app.after_request
def add_cors_headers(response):
    """添加CORS头信息，支持跨域访问"""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, PATCH, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response

if __name__ == '__main__':
    # 配置Flask支持中文调试信息
    import sys
    import codecs
    
    # 确保标准输出支持中文
    if sys.stdout.encoding != 'UTF-8':
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    if sys.stderr.encoding != 'UTF-8':
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
    
    app.run(host='0.0.0.0', port=5000, debug=True)
