'use strict';
(() => {
  const find = id => document.getElementById(id);
  const steps = [
    {
      label: '登录', title: '先登录一次，就能开始', target: '.account',
      intro: '登录在 Geocaching 官方网页完成，助手使用专用的火狐窗口。',
      instructions: ['点击右上角“登录 Geocaching”，在新开的官网标签页自行登录。', '切回“寻宝手记”标签页，点击“检查登录”；看到“已登录”即可。', '已经登录的话，直接看下一步。下次使用，双击“启动日志助手.cmd”即可。'],
      tip: '使用期间保留专用火狐窗口。密码只填在官网，不需要发到聊天中。'
    },
    {
      label: '地点', title: '一篇手记，对应一次真实寻宝', target: '#gc',
      intro: '先点左侧“＋ 新建日志”，把不同藏宝点的回忆分开保存。',
      instructions: ['在“GC 编号或藏宝点链接”里粘贴官网的 GC 编号或链接。', '核对实际寻宝日期，再选择“找到了”“没找到”“留言”或“参加活动”。', '手记名字只用于帮你辨认草稿，可以不填。'],
      tip: '日期默认是今天，补写旧日志时记得改日期。草稿会自动保存在这台电脑。'
    },
    {
      label: '照片', title: '选几张照片，找回当时的记忆', target: '#drop',
      intro: '照片可以多选；暂时不想放照片，也能直接跳过这一步。',
      instructions: ['点击照片选择区，或把照片拖进来。按住 Ctrl 可选多张。', '每篇最多选 10 张 JPG、PNG 或 WebP；单张原图小于 24 MB。HEIC 请先转成 JPG。', '看缩略图确认选对照片，点右上角“×”可以移除；照片标题可以不填。'],
      tip: '助手只处理上传用的副本，会压缩并移除 EXIF（包括 GPS），原照片不会改变。'
    },
    {
      label: '描述', title: '点几句话，少敲一点字', target: '#chips',
      intro: '只点选当时实际发生的经历，比如“藏得巧妙”或“感谢藏主”。',
      instructions: ['点击描述词，选中的词会变绿；再点一次可以取消。', '想多说一点，就写在“还想补充一点”里；不补充也可以。', '最后读一遍“日志内容”，可以直接编辑正文。手动改好正文后，再点描述词或重新生成会重组文字。'],
      tip: '助手组合你选的话，不会从照片猜测经历。“没找到”时，请核对正文里没有“已签日志”等不符合实际的描述。'
    },
    {
      label: '预览', title: '先看预览，想发的时候再确认', target: '#publish',
      intro: '点击“预览并发布”只会打开预览窗口，此时还没有上传。',
      instructions: ['核对 GC 编号、实际日期、日志类型、正文和全部照片。', '有任何地方想改，点击“再改一下”，回到草稿继续编辑。', '只有点击预览里的“确认，一键发布”，日志和照片才会公开发布到 Geocaching.com。'],
      tip: '今天不想发布？直接收起教程、关掉网页也可以。下次从左侧“我的手记”继续。教程不会替你点击发布。'
    },
    {
      label: '之后', title: '发出后看结果，中途也能继续', target: '#drafts',
      intro: '左侧每篇手记都会显示进度，方便以后接着处理。',
      instructions: ['看到“已发布”，表示文字和所选照片都已完成；可点“到官网查看”核对。', '如果显示“照片待完成”，继续操作会补传未完成的照片；已经成功的文字不会重发。', '如果显示“待核对”，先打开官网确认，再关联已有 GL 编号或按提示处理；不要直接重复提交。'],
      tip: '正文发布后，请到官网编辑。以后随时点左侧“使用教程”，都能重新查看这六步。'
    }
  ];
  const dialog = find('guide');
  let step = 0;
  let highlightTimer;
  function seen() { try { localStorage.setItem('geolog-guide-v1', 'seen'); } catch (_) {} }
  function show() {
    const item = steps[step];
    find('guide-count').textContent = `第 ${step + 1} 步，共 ${steps.length} 步`;
    find('guide-title').textContent = item.title;
    find('guide-intro').textContent = item.intro;
    find('guide-instructions').replaceChildren(...item.instructions.map(text => {
      const li = document.createElement('li'); li.textContent = text; return li;
    }));
    find('guide-tip').textContent = item.tip;
    find('guide-prev').disabled = step === 0;
    find('guide-next').textContent = step === steps.length - 1 ? '看完了，回到手记 ✓' : '下一步 →';
    find('guide-steps').replaceChildren(...steps.map((entry, index) => {
      const button = document.createElement('button');
      button.textContent = `${index + 1} ${entry.label}`;
      button.className = index === step ? 'active' : '';
      if (index === step) button.setAttribute('aria-current', 'step');
      button.onclick = () => { step = index; show(); find('guide-title').focus(); };
      return button;
    }));
  }
  function open() {
    show();
    find('guide-resume').hidden = true;
    if (!dialog.open) dialog.showModal();
    find('guide-title').focus();
  }
  function close(resume) {
    seen();
    find('guide-resume').hidden = !resume;
    dialog.close();
  }
  find('guide-open').onclick = open;
  find('guide-resume').onclick = open;
  find('guide-close').onclick = () => close(false);
  dialog.addEventListener('cancel', () => { seen(); find('guide-resume').hidden = true; });
  find('guide-prev').onclick = () => { if (step > 0) step--; show(); find('guide-title').focus(); };
  find('guide-next').onclick = () => {
    if (step < steps.length - 1) { step++; show(); find('guide-title').focus(); }
    else { close(false); find('guide-open').focus(); }
  };
  find('guide-locate').onclick = () => {
    const target = document.querySelector(steps[step].target);
    if (!target) return;
    clearTimeout(highlightTimer);
    document.querySelectorAll('.guide-highlight').forEach(node => node.classList.remove('guide-highlight'));
    close(true);
    target.scrollIntoView({behavior: 'smooth', block: 'center'});
    target.classList.add('guide-highlight');
    highlightTimer = setTimeout(() => target.classList.remove('guide-highlight'), 5000);
  };
  try { if (!localStorage.getItem('geolog-guide-v1')) open(); } catch (_) { open(); }
})();
