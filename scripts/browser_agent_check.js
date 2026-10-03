// Execute with playwright-cli after logging in to the local preview.
async (page) => {
  const checks = [];
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const record = (id, passed, detail) => checks.push({ id, passed, detail });
  await page.setViewportSize({ width: 1440, height: 1080 });
  await page.getByRole('link', { name: '智能顾问', exact: true }).click();
  await page.locator('#agent-q').waitFor({ state: 'visible' });
  await page.waitForFunction(() => document.querySelector('#agent-model').value === 'qwen3.8-flash');
  if (await page.locator('#agent-use-profile').isChecked()) {
    await page.locator('.agent-profile-toggle').click();
  }
  record('BQA-01', await page.locator('#agent-model').inputValue() === 'qwen3.8-flash'
    && await page.locator('#agent-model option').count() === 1,
    'Model selector reflects configured provider, not obsolete hardcoded models');
  const ask = async (question) => {
    await page.locator('#agent-q').fill(question);
    const response = page.waitForResponse(r => r.url().includes('/api/agent/ask?'));
    await page.locator('#agent-send').click();
    const http = await response;
    const data = await http.json();
    await page.waitForFunction(() => !document.querySelector('#agent-send').disabled);
    return { data, url: http.url(), text: await page.locator('.msg-row-agent').last().innerText() };
  };
  let result = await ask('2026年第七届MathorCup数学应用挑战赛（大数据竞赛）报名截止是哪天几点？');
  record('BQA-02', result.text.includes('2026-10-23 12:00') && result.data.resolved_competition === 'mathorcup_data_2026',
    'Official deadline rendered through the real HTTP API');
  record('BQA-03', await page.locator('#agent-context-clear').isVisible()
    && (await page.locator('#agent-cid option').first().textContent()).includes('MathorCup'),
    'Conversation context is visible and can be cleared');
  result = await ask('这个比赛几个人一队？');
  record('BQA-04', result.data.resolved_competition === 'mathorcup_data_2026'
    && result.url.includes('context_competition_id=mathorcup_data_2026'),
    'Natural followup sends tab-local context and remains in the same contest');
  await page.locator('#agent-context-clear').click();
  record('BQA-05', !(await page.locator('#agent-context-clear').isVisible())
    && await page.locator('#agent-cid').inputValue() === ''
    && await page.locator('#agent-cid option').first().textContent() === '自动识别',
    'Clear resets both explicit selection and conversation context');
  await page.locator('#agent-cid').selectOption('cocr_2026');
  result = await ask('帮我为这个比赛制定一周备赛计划');
  record('BQA-06', result.text.includes('候选') && result.text.includes('第7天')
    && await page.locator('.msg-row-agent').last().locator('.agent-create-task').count() === 0,
    'Candidate plan uses real API response, retains warning, and cannot create official tasks');
  await page.locator('#agent-context-clear').click();
  result = await ask('明年宇宙高校创新杯报名要多少钱？');
  record('BQA-07', !result.data.resolved_competition && !result.data.citations.length,
    'Unknown event is not replaced by a real or previously selected contest');
  await page.screenshot({ path: 'output/playwright/qa-agent-desktop.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  const bounds = await page.evaluate(() => {
    const send = document.querySelector('#agent-send').getBoundingClientRect();
    const context = document.querySelector('#agent-cid').getBoundingClientRect();
    return { noOverflow: document.documentElement.scrollWidth <= innerWidth,
      sendFits: send.left >= 0 && send.right <= innerWidth && send.bottom <= innerHeight,
      contextFits: context.left >= 0 && context.right <= innerWidth };
  });
  record('BQA-08', bounds.noOverflow && bounds.sendFits && bounds.contextFits,
    '390px mobile context and send controls fit without horizontal overflow');
  await page.screenshot({ path: 'output/playwright/qa-agent-mobile.png' });
  record('BQA-09', errors.length === 0, 'No browser page errors during this workflow');
  return { executed_at: new Date().toISOString(), mode: 'real_browser_local_http_no_response_mocking',
    profile_sent: false, viewports: ['1440x1080', '390x844'], errors, checks,
    summary: { passed: checks.filter(check => check.passed).length, total: checks.length } };
}
