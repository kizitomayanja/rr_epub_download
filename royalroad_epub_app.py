import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
from ebooklib import epub
import io
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def scrape_royalroad(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
    try:
        session = requests.Session()
        retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        session.mount('https://', HTTPAdapter(max_retries=retries))
        response = session.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # Book title
        title_tag = soup.find('h1')
        title = title_tag.text.strip() if title_tag else 'Unknown Title'
        logger.debug(f"Title: {title}")

        # Author
        author_tag = soup.find('a', href=re.compile(r'/profile/\d+'))
        author = author_tag.text.strip() if author_tag else 'Unknown Author'
        logger.debug(f"Author: {author}")

        # Chapters
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
                        logger.debug(f"Found chapter: {ch_title}")
        return title, author, chapters
    except Exception as e:
        logger.error(f"Error scraping {url}: {str(e)}")
        raise

def get_chapter_content(ch_url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    
    for attempt in range(3):
        try:
            response = session.get(ch_url, headers=headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            content_div = soup.find('div', class_='chapter-content')
            if not content_div:
                logger.warning(f"No content found at {ch_url}")
                return '<p>Chapter content not found.</p>'

            # Clean up
            for p in content_div.find_all('p'):
                p_text = p.text.strip()
                if p_text == 'Advertisement' or '[Remove]' in p_text or p_text.startswith("Author's Comment:"):
                    p.decompose()

            for div in content_div.find_all('div', class_=re.compile(r'.*Actions.*')):
                div.decompose()

            # Remove scripts but preserve paragraph structure
            for script in content_div.find_all('script'):
                script.decompose()

            # Convert content to string, preserving HTML structure
            html = str(content_div)
            time.sleep(1)  # Rate limiting
            return html
        except Exception as e:
            logger.error(f"Attempt {attempt + 1} failed for {ch_url}: {str(e)}")
            if attempt == 2:
                return f'<p>Error fetching chapter: {str(e)}</p>'
            time.sleep(2 ** attempt)  # Exponential backoff
    return '<p>Chapter content not found after retries.</p>'

def create_epub(title, author, chapters, output_buffer=None):
    try:
        book = epub.EpubBook()
        book.set_identifier(f'royalroad_{re.sub(r"[^a-zA-Z0-9]", "", title.lower())}')
        book.set_title(title)
        book.set_language('en')
        book.add_author(author)

        # Add basic CSS for paragraph spacing
        style = '''
        p { margin-bottom: 1em; line-height: 1.5; }
        '''
        css = epub.EpubItem(
            uid="style",
            file_name="style/style.css",
            media_type="text/css",
            content=style.encode('utf-8')
        )
        book.add_item(css)

        chapter_items = []
        progress_bar = st.progress(0)
        total_chapters = len(chapters)

        for i, (ch_title, ch_url) in enumerate(chapters, 1):
            st.write(f'Fetching chapter {i}: {ch_title}')
            logger.debug(f"Fetching chapter {i}: {ch_title} ({ch_url})")
            content_html = get_chapter_content(ch_url)
            chapter = epub.EpubHtml(title=ch_title, file_name=f'chap_{i:03d}.xhtml', lang='en')
            # Wrap content in proper HTML structure with CSS
            chapter_content = f'''
            <html>
            <head>
                <title>{ch_title}</title>
                <link rel="stylesheet" type="text/css" href="style/style.css" />
            </head>
            <body>
                <h1>{ch_title}</h1>
                {content_html}
            </body>
            </html>
            '''
            try:
                chapter.content = chapter_content.encode('utf-8')
            except Exception as e:
                logger.error(f"Error encoding chapter {ch_title}: {str(e)}")
                chapter.content = '<p>Error encoding chapter content.</p>'.encode('utf-8')
            book.add_item(chapter)
            chapter_items.append(chapter)
            progress_bar.progress(i / total_chapters)

        # Cover page
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

        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ['nav', cover_html] + chapter_items

        if output_buffer:
            try:
                epub.write_epub(output_buffer, book, {})
                logger.debug("Wrote EPUB to buffer")
            except Exception as e:
                logger.error(f"Error writing EPUB to buffer: {str(e)}")
                raise
        else:
            safe_title = re.sub(r'[^a-zA-Z0-9]', '_', title.lower())
            output_file = f'{safe_title}.epub'
            try:
                epub.write_epub(output_file, book, {})
                logger.debug(f"Wrote EPUB to file: {output_file}")
            except Exception as e:
                logger.error(f"Error writing EPUB to file: {str(e)}")
                raise

        return True
    except Exception as e:
        logger.error(f"Error creating EPUB: {str(e)}")
        raise

def main():
    if 'epub_generated' not in st.session_state:
        st.session_state.epub_generated = False
        st.session_state.epub_buffer = None
        st.session_state.title = None

    st.title('🗡️ Royal Road Novel to EPUB Converter')
    st.write('Enter a Royal Road fiction URL below to scrape chapters and generate a downloadable EPUB. For personal use only.')

    url = st.text_input('Fiction URL', placeholder='https://www.royalroad.com/fiction/12345/book-title', help='e.g., https://www.royalroad.com/fiction/119563/nexus-rebirth-of-the-dragon-monarch')

    if st.button('Generate EPUB', type='primary', use_container_width=True):
        if not url:
            st.error('Please enter a valid URL.')
            return

        # Reset session state
        st.session_state.epub_generated = False
        st.session_state.epub_buffer = None
        st.session_state.title = None

        with st.spinner('Scraping book info and chapters... This may take a while for long novels.'):
            try:
                title, author, chapters = scrape_royalroad(url)
                if not chapters:
                    st.error('No chapters found. Double-check the URL.')
                    return

                st.success(f'Found: **{title}** by **{author}** ({len(chapters)} chapters)')
                st.session_state.title = title

                # Generate EPUB in memory
                epub_buffer = io.BytesIO()
                success = create_epub(title, author, chapters, output_buffer=epub_buffer)
                if not success:
                    st.error('Failed to create EPUB.')
                    return

                # Check buffer size
                epub_buffer.seek(0)
                buffer_size = len(epub_buffer.getvalue())
                logger.debug(f"Buffer size: {buffer_size} bytes")
                if buffer_size == 0:
                    st.error('Generated EPUB is empty. Check logs for errors.')
                    safe_title = re.sub(r'[^a-zA-Z0-9]', '_', title.lower())
                    create_epub(title, author, chapters)  # Save to file
                    st.warning(f'EPUB was empty. Saved to {safe_title}.epub for debugging.')
                    return

                st.session_state.epub_buffer = epub_buffer.getvalue()
                st.session_state.epub_generated = True

            except Exception as e:
                st.error(f'Error: {str(e)}. Try a different URL or check your connection.')
                logger.error(f"Main error: {str(e)}")

    if st.session_state.epub_generated and st.session_state.epub_buffer:
        safe_title = re.sub(r'[^a-zA-Z0-9]', '_', st.session_state.title.lower())
        st.download_button(
            label=f'Download {st.session_state.title}.epub',
            data=st.session_state.epub_buffer,
            file_name=f'{safe_title}.epub',
            mime='application/epub+zip',
            use_container_width=True
        )
        st.balloons()

if __name__ == '__main__':
    main()