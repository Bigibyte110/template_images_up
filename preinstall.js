const { execSync } = require('child_process');

try {
  console.log('Installing Playwright browsers...');
  execSync('npx playwright install chromium', { stdio: 'inherit' });
} catch (error) {
  console.error('Failed to install Playwright:', error.message);
  process.exit(1);
}