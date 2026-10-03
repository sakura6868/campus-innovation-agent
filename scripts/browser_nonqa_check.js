// Run through playwright-cli against the isolated local QA server only.
async (page) => {
  const results = [];
  const record = (id, passed, detail) => results.push({ id, passed, detail });
  const go = async (hash, selector) => {
    await page.evaluate((value) => { location.hash = value; }, hash);
    await page.locator(selector).waitFor({ state: 'visible' });
    await page.waitForTimeout(350);
  };
  await go('#/profile', '#f-grade');
  await page.locator('#f-education').selectOption('研究生');
  await page.locator('#f-grade').selectOption('研一');
  await page.getByRole('button', { name: '保存画像', exact: true }).click();
  await page.waitForTimeout(500);
  await go('#/profile', '#f-grade');
  record('B01', await page.locator('#f-education').inputValue() === '研究生'
    && await page.locator('#f-grade').inputValue() === '研一', '研一已通过表单保存并重新加载');
  await page.locator('#f-team').fill('4');
  await page.getByRole('button', { name: '保存画像', exact: true }).click();
  await page.waitForTimeout(500);
  await go('#/detail/mathorcup_data_2026', '#view-detail');
  const detail = await page.locator('#view-detail').innerText();
  record('B02', await page.getByRole('button', { name: '加入我的项目', exact: true }).count() === 0
    && detail.includes('预计团队人数超过上限'), '四人画像详情无加入按钮，并展示个人门控原因');
  const directStatus = await page.evaluate(async () => {
    const response = await fetch('/api/users/test/projects', {
      method: 'POST', headers: { 'Content-Type': 'application/json',
        Authorization: 'Bearer ' + sessionStorage.getItem('cia_access_token') },
      body: JSON.stringify({ competition_id: 'mathorcup_data_2026' }),
    });
    return response.status;
  });
  record('B03', directStatus === 409, '绕过前端直接创建项目返回409');
  await page.screenshot({ path: 'output/playwright/nonqa-ineligible-desktop.png' });
  await go('#/projects', '#view-projects');
  record('B04', (await page.locator('#view-projects').innerText()).includes('参赛条件或来源状态已变化'),
    '既有项目保留并出现资格状态变化提醒');
  await page.screenshot({ path: 'output/playwright/nonqa-project-warning-desktop.png' });
  await go('#/detail/cocr_2026', '#view-detail');
  record('B05', await page.getByRole('button', { name: '加入我的项目', exact: true }).count() === 0
    && await page.getByRole('link', { name: '访问官网', exact: true }).count() === 1,
    '汇总候选可看官网但不能加入正式项目');
  await go('#/profile', '#f-grade');
  await page.locator('#f-team').fill('3');
  await page.getByRole('button', { name: '保存画像', exact: true }).click();
  await page.waitForTimeout(500);
  await go('#/detail/ncccu_digital_2026', '#view-detail');
  record('B06', (await page.locator('#view-detail').innerText()).includes('报名中')
    && await page.getByRole('button', { name: '加入我的项目', exact: true }).count() === 1,
    '已进入制作期的数字媒体赛仍按真实报名日期开放');
  await page.getByRole('button', { name: '加入我的项目', exact: true }).click();
  await page.waitForTimeout(500);
  const planCheck = await page.evaluate(async () => {
    const response = await fetch('/api/users/test/projects', {
      headers: { Authorization: 'Bearer ' + sessionStorage.getItem('cia_access_token') },
    });
    const project = (await response.json()).find((item) => item.competition_id === 'ncccu_digital_2026');
    const created = new Date(project.created_at + 'Z');
    const start = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(created);
    const dates = project.items.filter((item) => item.item_type === 'task' && item.due_date).map((item) => item.due_date);
    return { noPastTasks: project.items.every((item) => !item.due_date || item.due_date >= start),
      monotonic: JSON.stringify(dates) === JSON.stringify([...dates].sort()) };
  });
  record('B07', planCheck.noPastTasks && planCheck.monotonic, '新项目日期不早于创建日且阶段顺序一致');
  await page.setViewportSize({ width: 390, height: 844 });
  await go('#/profile', '#f-grade');
  const bounds = await page.evaluate(() => {
    const grade = document.querySelector('#f-grade');
    const rect = grade.getBoundingClientRect();
    return { fits: rect.width > 0 && rect.right <= innerWidth && rect.left >= 0,
      noOverflow: document.documentElement.scrollWidth <= innerWidth };
  });
  record('B08', bounds.fits && bounds.noOverflow, '390px手机画像年级控件无横向溢出');
  await page.locator('#f-grade').scrollIntoViewIfNeeded();
  await page.screenshot({ path: 'output/playwright/nonqa-profile-mobile.png' });
  await go('#/agent', '#agent-q');
  await page.route('**/api/agent/ask?*', async (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({
      answer: '候选信息，仅检查执行按钮，不调用问答接口。', intent: 'chat',
      resolved_competition: 'cocr_2026', resolved_name: '候选赛事', pending_review: false,
      gate: { eligible: false, reasons: [] }, citations: [], recommendations: [],
      trace: [], web_results: [], teammate_matches: [],
    }),
  }));
  await page.locator('#agent-q').fill('候选执行按钮状态检查');
  await page.locator('#agent-send').click();
  await page.waitForTimeout(500);
  record('B09', await page.locator('.agent-create-task').count() === 0,
    '候选模拟响应不显示转任务按钮；浏览器拦截请求，没有调用模型');
  await page.screenshot({ path: 'output/playwright/nonqa-candidate-task-mobile.png' });
  await page.unroute('**/api/agent/ask?*');
  return results;
}
