import re
from bs4 import BeautifulSoup

path = '/home/ubuntu/upload/pages.coupang.com_p_121237_sourceType_oms_goldbox_1787360362874.html'
soup = BeautifulSoup(open(path, encoding='utf-8'), 'html.parser')
rows = []
for anchor in soup.select('a[href*="/vp/products/"]'):
    card = anchor.select_one('.discount-product-unit') or anchor
    title_node = card.select_one('.info_section__title, .info-section__title, [class*="title"]')
    sale_node = card.select_one('.price_info__discount')
    base_node = card.select_one('.price_info__base')
    match = re.search(r'/vp/products/(\d+).*?[?&]itemId=(\d+).*?[?&]vendorItemId=(\d+)', anchor.get('href', ''))
    image = card.select_one('.discount-product-unit__product_image img') or card.select_one('img')
    if title_node and sale_node and match:
        rows.append((title_node.get_text(' ', strip=True), sale_node.get_text(' ', strip=True), match.groups(), image.get('src', '') if image else ''))
print('CANDIDATE_COUNT', len(rows))
for row in sorted(rows, key=lambda item: int(re.sub(r'[^0-9]', '', item[1]))):
    print(row)
