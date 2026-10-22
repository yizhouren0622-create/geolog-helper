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
      instructions: ['选常用地区，输入名称或经纬度；拖动地图后点“搜索当前地图范围”，在结果或标记上点“选择”。也可直接粘贴 GC 编号。', '想用官网？点“官网地图”，在专用火狐里打开具体藏宝点详情，再回助手点“带回官网选中的点”。', '核对实际日期，点选“找到了”或“没找到 DNF”等日志类型。不同藏宝点建议新建不同手记。'],
      tip: '地图显示账号实际可见的数据；缺少坐标的点只显示在列表。日期默认今天，补写旧日志时记得改日期。'
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
      instructions: ['FTF（首找）和 TFTC（感谢藏主）有独立按钮；FTF 只在“找到了”类型下可选。', '点击描述词后会加入正文，再点一次可移除对应的句子；你手动写的其他文字会保留。', '最后读一遍正文。点“按选择重新生成正文”会替换正文，手动编辑过时会先请你确认。'],
      tip: '选择 DNF 会关闭找到、首找和签名描述。助手不会从照片猜测经历，仍请核对最终正文符合实际。'
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
      tip: '页面下方“藏宝点数据与自动更新”显示六个重点地区每15天的更新状态；全球需配置获授权CSV来源后才每6个月更新。正文发布后请到官网编辑。'
    }
  ];
  const dialog = find('guide');
  let step = 0;
  let highlightTimer;
  function seen() { try { localStorage.setItem('geolog-guide-v2', 'seen'); } catch (_) {} }
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
  try { if (!localStorage.getItem('geolog-guide-v2')) open(); } catch (_) { open(); }
})();
