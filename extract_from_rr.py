import requests
from bs4 import BeautifulSoup
import re
from ebooklib import epub

def scrape_royalroad(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')

    # Book title
    title_tag = soup.find('h1')
    title = title_tag.text.strip() if title_tag else 'Unknown Title'

    # Author (find the profile link in the header/synopsis area)
    author_tag = soup.find('a', href=re.compile(r'/profile/\d+'))
    author = author_tag.text.strip() if author_tag else 'Unknown Author'

    # Chapters (parse the chapters table)
    chapters = []
    table = soup.find('table')
    if table:
        rows = table.find_all('tr')[1:]  # Skip header row
        for row in rows:
            tds = row.find_all('td')
            if len(tds) >= 2:
                a = tds[0].find('a')
                if a and '/chapter/' in a.get('href', ''):
                    ch_title = a.text.strip()
                    ch_url = 'https://www.royalroad.com' + a['href'] if a['href'].startswith('/') else a['href']
                    chapters.append((ch_title, ch_url))

    return title, author, chapters

def get_chapter_content(ch_url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
    response = requests.get(ch_url, headers=headers)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')

    content_div = soup.find('div', class_='chapter-content')
    if not content_div:
        return '<p>Chapter content not found.</p>'

    # Clean up: Remove advertisement and author notes
    for p in content_div.find_all('p'):
        p_text = p.text.strip()
        if p_text == 'Advertisement' or '[Remove]' in p_text or p_text.startswith("Author's Comment:"):
            p.decompose()

    # Remove any remaining action elements
    for div in content_div.find_all('div', class_=re.compile(r'.*Actions.*')):
        div.decompose()

    # Get the full HTML for better formatting preservation
    html = str(content_div)
    # Basic cleanup for extra whitespace/scripts
    html = re.sub(r'<script.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'\s+', ' ', html)  # Normalize whitespace

    return html

def create_epub(title, author, chapters, output_filename=None):
    if not output_filename:
        safe_title = re.sub(r'[^a-zA-Z0-9]', '_', title.lower())
        output_filename = f'{safe_title}.epub'

    book = epub.EpubBook()
    book.set_identifier(f'royalroad_{re.sub(r"[^a-zA-Z0-9]", "", title.lower())}')
    book.set_title(title)
    book.set_language('en')
    book.add_author(author)

    chapter_items = []
    for i, (ch_title, ch_url) in enumerate(chapters, 1):
        print(f'Fetching chapter {i}: {ch_title}')  # Progress indicator
        content_html = get_chapter_content(ch_url)
        chapter = epub.EpubHtml(title=ch_title, file_name=f'chap_{i:03d}.xhtml', lang='en')
        chapter.content = content_html.encode('utf-8')
        book.add_item(chapter)
        chapter_items.append(chapter)

    # Simple cover page with title
    cover_html = epub.EpubHtml(title='Cover', file_name='cover.xhtml', lang='en')
    cover_html.content = f'''
    <html>
    <head><title>{title}</title></head>
    <body>
        <h1 style="text-align: center; font-size: 2em; margin-top: 50px;">{title}</h1>
        <p style="text-align: center; font-size: 1.2em;">By {author}</p>
    </body>
    </html>
    '''.encode('utf-8')
    book.add_item(cover_html)

    # Table of contents
    book.toc = (epub.Link('cover.xhtml', 'Cover', 'cover'),) + tuple(
        epub.Link(ch.file_name, ch.title, 'chapter') for ch in chapter_items
    )

    # Add metadata/navigation
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Spine (reading order)
    book.spine = ['nav', 'cover.xhtml'] + [ch.file_name for ch in chapter_items]

    # Write EPUB
    epub.write_epub(output_filename, book)
    print(f'EPUB saved as {output_filename}')

if __name__ == '__main__':
    url = input('Enter Royal Road fiction URL: ')
    title, author, chapters = scrape_royalroad(url)
    print(f'Title: {title}')
    print(f'Author: {author}')
    print(f'Found {len(chapters)} chapters')
    if chapters:
        create_epub(title, author, chapters)
    else:
        print('No chapters found. Check the URL.')