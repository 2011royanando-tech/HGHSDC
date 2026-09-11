import unittest
import urllib.parse
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

@unittest.skipUnless(SELENIUM_AVAILABLE, "Selenium is not installed")
class TestBrowserEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Read HTML, CSS, and JS files
        css_win = open('/working_dir/c_3f465ce2262cd45b/debate_tab/app/static/css/windows11.css').read()
        css_sheet = open('/working_dir/c_3f465ce2262cd45b/debate_tab/app/static/css/spreadsheet.css').read()
        css_bracket = open('/working_dir/c_3f465ce2262cd45b/debate_tab/app/static/css/bracket.css').read()
        css_timer = open('/working_dir/c_3f465ce2262cd45b/debate_tab/app/static/css/timer.css').read()

        js_i18n = open('/working_dir/c_3f465ce2262cd45b/debate_tab/app/static/js/i18n.js').read()
        js_audio = open('/working_dir/c_3f465ce2262cd45b/debate_tab/app/static/js/audio.js').read()
        js_timer = open('/working_dir/c_3f465ce2262cd45b/debate_tab/app/static/js/timer.js').read()
        js_sheet = open('/working_dir/c_3f465ce2262cd45b/debate_tab/app/static/js/spreadsheet.js').read()
        js_bracket = open('/working_dir/c_3f465ce2262cd45b/debate_tab/app/static/js/bracket.js').read()

        html_content = f'''<!DOCTYPE html>
<html>
<head>
  <style>{css_win}</style>
  <style>{css_sheet}</style>
  <style>{css_bracket}</style>
  <style>{css_timer}</style>
</head>
<body>
  <header class="win-navbar">
    <div class="brand-container">
      <div class="brand-logo">T</div>
      <div class="brand-title" data-i18n="app_title">TRADITIONAL DEBATE TAB</div>
    </div>
    <div class="nav-actions">
      <button class="btn btn-secondary btn-sm" id="lang-toggle-btn" onclick="window.i18n.toggleLanguage()">বাংলা</button>
    </div>
  </header>
  <div id="main-view" style="padding: 2rem;">
    <div id="bracket-mount"></div>
    <div id="sheet-mount" style="margin-top: 2rem;"></div>
  </div>
  <script>{js_i18n}</script>
  <script>{js_audio}</script>
  <script>{js_timer}</script>
  <script>{js_sheet}</script>
  <script>{js_bracket}</script>
</body>
</html>'''

        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')

        data_url = 'data:text/html;charset=utf-8,' + urllib.parse.quote(html_content)

        service = Service(executable_path='/usr/bin/chromedriver')
        cls.driver = webdriver.Chrome(service=service, options=options)
        cls.driver.get(data_url)

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()

    def test_01_brand_and_i18n_toggle(self):
        brand = self.driver.find_element(By.CLASS_NAME, 'brand-title')
        self.assertEqual(brand.text, 'TRADITIONAL DEBATE TAB')

        # Toggle to Bangla
        lang_btn = self.driver.find_element(By.ID, 'lang-toggle-btn')
        lang_btn.click()
        self.assertEqual(brand.text, 'ঐতিহ্যবাহী বিতর্ক ট্যাব')

        # Toggle back to English
        lang_btn.click()
        self.assertEqual(brand.text, 'TRADITIONAL DEBATE TAB')

    def test_02_fifa_style_bracket_render(self):
        bracket_data = {
            'matches': [
                {
                    'id': i+1,
                    'match_number': i+1,
                    'team1_name': f'Team {i*2+1}',
                    'team2_name': f'Team {i*2+2}',
                    'is_published': 1,
                    'team1_aggregate': 130.0,
                    'team2_aggregate': 120.0,
                    'winner_id': 1
                } for i in range(15)
            ]
        }
        self.driver.execute_script('window.renderBracket("bracket-mount", arguments[0], true);', bracket_data)
        cards = self.driver.find_elements(By.CLASS_NAME, 'bracket-match-card')
        self.assertEqual(len(cards), 15)

    def test_03_spreadsheet_calculation_and_totals(self):
        sheet_mock = {
            'scorecard': {'id': 1, 'status': 'DRAFT'},
            'criteria': [
                {'id': 1, 'name': 'Logic', 'max_marks': 30.0},
                {'id': 2, 'name': 'Delivery', 'max_marks': 25.0}
            ],
            'scores': []
        }
        match_mock = {
            'id': 1,
            'match_number': 1,
            'team1_id': 101,
            'team1_name': 'Dhaka Titans',
            'team2_id': 102,
            'team2_name': 'Notre Dame Gold'
        }
        self.driver.execute_script('''
            window.sheet = new window.AdjudicationSpreadsheet("sheet-mount");
            window.sheet.loadData(arguments[0], arguments[1], [], []);
        ''', sheet_mock, match_mock)

        inputs = self.driver.find_elements(By.CLASS_NAME, 'sheet-input')
        self.assertEqual(len(inputs), 12) # 2 teams * 3 speakers * 2 criteria

        # Input speaker marks and test calculation
        self.driver.execute_script('''
            window.sheet.setScore(101, 1, 1, 25.0);
            window.sheet.setScore(101, 1, 2, 20.0);
            window.sheet.setScore(101, 2, 1, 28.0);
            window.sheet.setScore(101, 2, 2, 22.0);
            window.sheet.setScore(101, 3, 1, 27.0);
            window.sheet.setScore(101, 3, 2, 21.0);
        ''')
        t1_total = self.driver.find_element(By.ID, 'team-total-101').text
        self.assertEqual(t1_total, '143.00')

    def test_04_timer_and_audio_synthesis(self):
        # Trigger audio synthesis test
        self.driver.execute_script('window.debateAudio.testAudio();')
        # Test timer tick and format
        time_str = self.driver.execute_script('return window.debateTimer.formatTime(180);')
        self.assertEqual(time_str, '03:00')
        time_warn = self.driver.execute_script('return window.debateTimer.formatTime(60);')
        self.assertEqual(time_warn, '01:00')

if __name__ == '__main__':
    unittest.main()
