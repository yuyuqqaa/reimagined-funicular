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

def handle_html_rewrite(text, original_url):
    """处理HTML重写，修复相对链接"""
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
    modified_text = re.sub(
        r'<(a|img)([^>]*(href|src)=["\'])(?!https?://|//|data:|javascript:)([^"\']+)',
        lambda m: f'<{m.group(1)}{m.group(2)}{mirror_base}/{m.group(4)}',
        text,
        flags=re.IGNORECASE
    )
    
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
        
        # 处理HTML重写
        if (ENABLE_MODIFICATION and 
            response.headers.get('content-type', '').startswith('text/html')):
            
            content = response.text
            
            # 重写HTML内容
            modified_content = handle_html_rewrite(content, request.url)
            
            # 移除限制性头信息
            response_headers = remove_restrictive_headers(response.headers)
            
            return Response(
                modified_content,
                status=response.status_code,
                headers=response_headers
            )
        
        # 对于非HTML内容，流式传输以提高性能
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

# 更高级的HTML重写版本（可选）
def advanced_html_rewrite(text, base_url):
    """更高级的HTML重写，处理更多标签和属性"""
    mirror_base = f"{request.scheme}://{request.host}{request.path}"
    
    # 需要重写的标签和属性
    tags_to_rewrite = {
        'a': ['href'],
        'img': ['src'],
        'link': ['href'],
        'script': ['src'],
        'form': ['action'],
        'iframe': ['src']
    }
    
    modified_text = text
    
    for tag, attributes in tags_to_rewrite.items():
        for attr in attributes:
            # 匹配相对路径和根路径相对路径
            pattern = rf'<{tag}([^>]*){attr}=["\']((?!https?://|//|data:|javascript:)[^"\']*)["\']'
            
            def replace_callback(match):
                full_match = match.group(0)
                tag_attrs = match.group(1)
                path = match.group(2)
                
                # 跳过特殊路径
                if path.startswith(('http://', 'https://', '//', 'data:', 'javascript:', 'mailto:', 'tel:')):
                    return full_match
                
                # 处理绝对路径（以/开头）
                if path.startswith('/'):
                    path = path[1:]
                
                return f'<{tag}{tag_attrs}{attr}="{mirror_base}/{path}"'
            
            modified_text = re.sub(pattern, replace_callback, modified_text, flags=re.IGNORECASE)
    
    return modified_text



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
