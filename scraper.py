import requests
import json
import time
import re
import random
from datetime import datetime
from bs4 import BeautifulSoup
import cloudscraper
from fake_useragent import UserAgent
import logging
import cachetools
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

class InstagramScraper:
    def __init__(self):
        self.session = self._create_session()
        self.ua = UserAgent()
        self.request_count = 0
        self.cache = cachetools.TTLCache(maxsize=100, ttl=300)  # 5 minute cache
        
        # Instagram endpoints
        self.endpoints = {
            'profile': 'https://www.instagram.com/{}/',
            'profile_json': 'https://www.instagram.com/api/v1/users/web_profile_info/?username={}',
        }
        
        logger.info("InstagramScraper initialized")
    
    def _create_session(self):
        """Create session with cloudscraper"""
        try:
            scraper = cloudscraper.create_scraper(
                browser={
                    'browser': 'chrome',
                    'platform': 'windows',
                    'mobile': False
                }
            )
            return scraper
        except Exception as e:
            logger.warning(f"Cloudscraper failed, using requests: {str(e)}")
            return requests.Session()
    
    def _get_headers(self, user_agent: str = None):
        """Generate headers"""
        headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0',
        }
        headers['User-Agent'] = user_agent if user_agent else self.ua.random
        return headers
    
    def _make_request(self, url: str, client_ip: str = None, user_agent: str = None) -> Optional[requests.Response]:
        """Make HTTP request"""
        # Rate limiting
        time.sleep(random.uniform(1.0, 2.0))
        
        headers = self._get_headers(user_agent)
        
        # Add client IP to headers if provided
        if client_ip:
            headers['X-Forwarded-For'] = client_ip
            headers['X-Real-IP'] = client_ip
        
        try:
            response = self.session.get(
                url,
                headers=headers,
                timeout=15,
                allow_redirects=True
            )
            
            self.request_count += 1
            logger.debug(f"Request to {url} - Status: {response.status_code}")
            return response
            
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout for {url}")
        except requests.exceptions.ConnectionError:
            logger.warning(f"Connection error for {url}")
        except Exception as e:
            logger.error(f"Request error for {url}: {str(e)}")
        
        return None
    
    def scrape_profile(self, username: str, client_ip: str = None, user_agent: str = None) -> Dict:
        """Scrape Instagram profile data"""
        start_time = time.time()
        
        logger.info(f"Scraping profile: {username}")
        
        # Try multiple methods
        methods = [
            lambda: self._scrape_via_html(username, client_ip, user_agent),
            lambda: self._scrape_via_api(username, client_ip, user_agent),
        ]
        
        for method in methods:
            try:
                result = method()
                if result and 'error' not in result:
                    extraction_time = int((time.time() - start_time) * 1000)
                    result['extraction_time'] = extraction_time
                    result['data_points'] = self._count_data_points(result)
                    result['cached'] = False
                    result['used_ip'] = client_ip or "direct"
                    
                    return result
            except Exception as e:
                logger.debug(f"Method failed: {str(e)}")
                continue
        
        return {
            "error": "SCRAPING_FAILED",
            "message": "All scraping methods failed",
            "used_ip": client_ip or "direct"
        }
    
    def _scrape_via_html(self, username: str, client_ip: str = None, user_agent: str = None) -> Dict:
        """Scrape via HTML parsing"""
        try:
            url = self.endpoints['profile'].format(username)
            response = self._make_request(url, client_ip, user_agent)
            
            if not response or response.status_code != 200:
                return {"error": "REQUEST_FAILED"}
            
            html = response.text
            
            # Check for private account
            if 'This Account is Private' in html or 'account is private' in html.lower():
                return {"error": "PRIVATE_PROFILE"}
            
            # Check for non-existent account
            if 'Sorry, this page isn\'t available' in html:
                return {"error": "PROFILE_NOT_FOUND"}
            
            # Extract JSON data
            json_data = self._extract_json_from_html(html)
            
            if json_data:
                return self._parse_html_response(json_data, username)
            
            # Fallback to direct HTML parsing
            return self._parse_html_directly(html, username)
            
        except Exception as e:
            logger.error(f"HTML scraping error: {str(e)}")
            return {"error": "HTML_PARSING_FAILED"}
    
    def _scrape_via_api(self, username: str, client_ip: str = None, user_agent: str = None) -> Dict:
        """Use Instagram's API"""
        try:
            url = self.endpoints['profile_json'].format(username)
            response = self._make_request(url, client_ip, user_agent)
            
            if response and response.status_code == 200:
                data = response.json()
                user = data.get('data', {}).get('user', {})
                
                if not user:
                    return {"error": "USER_NOT_FOUND"}
                
                return self._parse_api_response(user)
            
        except Exception as e:
            logger.debug(f"API method failed: {str(e)}")
        
        return {"error": "API_FAILED"}
    
    def _extract_json_from_html(self, html: str) -> Optional[Dict]:
        """Extract JSON data from HTML"""
        try:
            # Look for window._sharedData pattern
            pattern = r'window\._sharedData\s*=\s*({.*?});'
            matches = re.search(pattern, html, re.DOTALL)
            
            if matches:
                try:
                    return json.loads(matches.group(1))
                except json.JSONDecodeError:
                    pass
            
            # Look for JSON-LD
            soup = BeautifulSoup(html, 'html.parser')
            script_tags = soup.find_all('script', type='application/ld+json')
            
            for script in script_tags:
                try:
                    return json.loads(script.string)
                except:
                    continue
            
        except Exception as e:
            logger.error(f"JSON extraction error: {str(e)}")
        
        return None
    
    def _parse_html_response(self, json_data: Dict, username: str) -> Dict:
        """Parse HTML JSON response"""
        try:
            # Navigate to user data
            user = None
            
            # Try different paths
            paths = [
                ['entry_data', 'ProfilePage', 0, 'graphql', 'user'],
                ['graphql', 'user'],
                ['user']
            ]
            
            for path in paths:
                current = json_data
                for key in path:
                    if isinstance(current, dict) and key in current:
                        current = current[key]
                    else:
                        current = None
                        break
                if current and 'username' in current:
                    user = current
                    break
            
            if not user:
                return {"error": "USER_DATA_NOT_FOUND"}
            
            # Extract profile data
            profile = {
                "identity": {
                    "username": user.get('username', username),
                    "full_name": user.get('full_name', ''),
                    "biography": user.get('biography', ''),
                    "external_url": user.get('external_url', ''),
                    "is_private": user.get('is_private', False),
                    "is_verified": user.get('is_verified', False),
                    "profile_pic_url": user.get('profile_pic_url_hd') or 
                                       user.get('profile_pic_url') or 
                                       ''
                },
                "statistics": {
                    "followers": user.get('edge_followed_by', {}).get('count', 0),
                    "following": user.get('edge_follow', {}).get('count', 0),
                    "posts": user.get('edge_owner_to_timeline_media', {}).get('count', 0)
                }
            }
            
            return {"profile": profile}
            
        except Exception as e:
            logger.error(f"HTML parsing error: {str(e)}")
            return {"error": "PARSING_ERROR"}
    
    def _parse_html_directly(self, html: str, username: str) -> Dict:
        """Direct HTML parsing fallback"""
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract meta tags
        meta_data = {}
        for meta in soup.find_all('meta'):
            prop = meta.get('property') or meta.get('name')
            content = meta.get('content')
            if prop and content:
                meta_data[prop] = content
        
        # Extract counts using regex
        followers = self._extract_count(html, r'(\d+(?:\.\d+)?[KM]?)\s*Followers')
        following = self._extract_count(html, r'(\d+(?:\.\d+)?[KM]?)\s*Following')
        posts = self._extract_count(html, r'(\d+(?:\.\d+)?[KM]?)\s*Posts')
        
        profile = {
            "identity": {
                "username": username,
                "full_name": meta_data.get('og:title', '').replace('• Instagram', '').strip(),
                "biography": meta_data.get('og:description', ''),
                "profile_pic_url": meta_data.get('og:image', ''),
                "is_private": 'private' in html.lower(),
                "is_verified": 'verified' in html.lower()
            },
            "statistics": {
                "followers": followers,
                "following": following,
                "posts": posts
            }
        }
        
        return {"profile": profile}
    
    def _parse_api_response(self, user_data: Dict) -> Dict:
        """Parse API response"""
        profile = {
            "identity": {
                "username": user_data.get('username', ''),
                "full_name": user_data.get('full_name', ''),
                "biography": user_data.get('biography', ''),
                "external_url": user_data.get('external_url', ''),
                "is_private": user_data.get('is_private', False),
                "is_verified": user_data.get('is_verified', False),
                "profile_pic_url": user_data.get('profile_pic_url_hd', user_data.get('profile_pic_url', ''))
            },
            "statistics": {
                "followers": user_data.get('edge_followed_by', {}).get('count', 0),
                "following": user_data.get('edge_follow', {}).get('count', 0),
                "posts": user_data.get('edge_owner_to_timeline_media', {}).get('count', 0)
            }
        }
        
        return {"profile": profile}
    
    def _extract_count(self, html: str, pattern: str) -> int:
        """Extract count using regex"""
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return self._parse_count_string(match.group(1))
        return 0
    
    def _parse_count_string(self, count_str: str) -> int:
        """Parse count strings like 1.2K, 5M"""
        try:
            count_str = count_str.replace(',', '').upper()
            
            if 'K' in count_str:
                num = float(count_str.replace('K', ''))
                return int(num * 1000)
            elif 'M' in count_str:
                num = float(count_str.replace('M', ''))
                return int(num * 1000000)
            else:
                return int(count_str)
        except:
            return 0
    
    def _count_data_points(self, data: Dict) -> int:
        """Count data points"""
        count = 0
        
        def recursive_count(obj):
            nonlocal count
            if isinstance(obj, dict):
                count += len(obj)
                for v in obj.values():
                    recursive_count(v)
            elif isinstance(obj, list):
                count += len(obj)
                for item in obj:
                    recursive_count(item)
        
        recursive_count(data)
        return count
    
    def test_connection(self, client_ip: str = None) -> Dict:
        """Test connection with client IP"""
        try:
            # Test with a simple request
            test_url = "https://www.instagram.com/instagram/"
            response = self._make_request(test_url, client_ip)
            
            if response and response.status_code == 200:
                return {
                    "status": "OPERATIONAL",
                    "message": "Scraper is working",
                    "used_ip": client_ip or "direct",
                    "timestamp": datetime.utcnow().isoformat()
                }
            else:
                return {
                    "status": "DEGRADED",
                    "message": "Connection test failed",
                    "used_ip": client_ip or "direct",
                    "timestamp": datetime.utcnow().isoformat()
                }
            
        except Exception as e:
            return {
                "status": "OFFLINE",
                "message": str(e),
                "used_ip": client_ip or "direct",
                "timestamp": datetime.utcnow().isoformat()
            }
