module.exports = async (req, res) => {
  const { chromium } = require('playwright-core');
  
  try {
    const browser = await chromium.launch({
      executablePath: '/tmp/playwright/chromium-*/chrome-linux/chrome',
      headless: true
    });
    
    const page = await browser.newPage();
    await page.goto('https://example.com');
    const title = await page.title();
    
    await browser.close();
    
    res.status(200).json({ 
      success: true, 
      title,
      message: 'Playwright works on Vercel!' 
    });
    
  } catch (error) {
    res.status(500).json({ 
      success: false, 
      error: error.message,
      tip: 'Run: npx playwright install chromium locally first'
    });
  }
};