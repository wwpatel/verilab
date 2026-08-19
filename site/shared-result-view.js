/* Shared three-layer disclosure result view: headline, then "View details"
   (exact step, real numbers, consequence, suggested_fix), then "Show
   technical detail" (raw extracted step, resolved capacity, generated
   code). Used identically by the marketing page's precomputed mockups,
   the Dashboard's live results, and the Stored Protocols viewer, so the
   same real rendering logic backs every one of them. */

window.VerilabResultView = (function () {
  const ICONS = {
    volume: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2c3 4 6 8.5 6 12a6 6 0 0 1-12 0c0-3.5 3-8 6-12z"/></svg>',
    order: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="12" r="2.5"/><path d="M8 7l8 4M8 17l8-4"/></svg>',
    tip: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 2h6l1 6-4 13-4-13 1-6z"/><path d="M9 8h6"/></svg>',
    data: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 1.6-2.5 2-2.5 4"/><line x1="12" y1="17" x2="12" y2="17.01"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M8 12.5l2.5 2.5L16 9"/></svg>',
    stop: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="8" y1="8" x2="16" y2="16"/><line x1="16" y1="8" x2="8" y2="16"/></svg>',
  };

  const STAGE_ORDER = [
    { stage: 'reading', label: 'Reading the protocol' },
    { stage: 'identify', label: 'Identifying containers and reagents' },
    { stage: 'checking', label: 'Checking volumes, order, and tip use' },
    { stage: 'generating', label: 'Preparing robot code' },
  ];

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === 'html') node.innerHTML = v;
      else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    }
    for (const c of (children || [])) {
      if (c == null) continue;
      node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return node;
  }

  function renderStageTracker(container, activeStage) {
    container.innerHTML = '';
    let reachedActive = false;
    for (const s of STAGE_ORDER) {
      const isActive = s.stage === activeStage;
      const isDone = !reachedActive && !isActive;
      if (isActive) reachedActive = true;
      const cls = isActive ? 'step active' : (reachedActive ? 'step' : 'step done');
      container.appendChild(el('span', { class: cls }, [s.label]));
    }
  }

  let violationSeq = 0;

  function renderResult(container, data) {
    container.innerHTML = '';

    const cleared = data.overall_status === 'CLEARED';
    const violations = (data.checks && data.checks.violations) || [];
    const errorCount = data.checks ? data.checks.error_count : 0;
    const warningCount = data.checks ? data.checks.warning_count : 0;

    const headline = cleared ? 'Cleared for the robot' : 'Do not run yet';
    let subline;
    if (violations.length === 0) {
      subline = 'No problems found. Reviewed against volume limits, step order, and tip reuse.';
    } else if (cleared) {
      subline = warningCount + ' item' + (warningCount === 1 ? '' : 's') + ' worth a second look, nothing blocking.';
    } else {
      subline = errorCount + ' problem' + (errorCount === 1 ? '' : 's') + ' found before this protocol can run.';
    }

    const banner = el('div', { class: 'vl-status-banner ' + (cleared ? 'cleared' : 'blocked') }, [
      el('div', { class: 'status-icon', html: cleared ? ICONS.check : ICONS.stop, 'aria-hidden': 'true' }, []),
      el('div', { class: 'status-text' }, [
        el('div', { class: 'headline' }, [headline]),
        el('div', { class: 'subline' }, [subline]),
      ]),
    ]);
    container.appendChild(banner);

    if (violations.length === 0) {
      const box = el('div', { class: 'vl-checked-box' }, [
        el('strong', {}, ['Checked against:']),
        el('ul', {}, (data.checks_run || []).map(c => el('li', {}, [c]))),
        el('p', { style: 'margin-top:10px;color:var(--gray);font-size:13px;' }, [data.checks_against_text || '']),
      ]);
      container.appendChild(box);
    } else {
      for (const v of violations) {
        container.appendChild(renderViolationCard(v));
      }
    }

    if (data.resources && data.resources.summary_text) {
      const box = el('div', { class: 'vl-resources-box' }, [
        el('h3', { style: 'color:var(--navy);font-family:Georgia,serif;font-size:15.5px;margin:0 0 8px;' }, ['Resources needed']),
        el('pre', { class: 'vl-code-readout' }, [data.resources.summary_text]),
      ]);
      container.appendChild(box);
    }

    if (data.generated_code) {
      const gc = data.generated_code;
      const box = el('div', { class: 'vl-code-box' }, [
        el('h3', { style: 'color:var(--navy);font-family:Georgia,serif;font-size:15.5px;margin:0 0 8px;' },
          [cleared ? 'Code ready to send to the robot' : 'Robot code']),
      ]);
      if (gc.skipped) {
        box.appendChild(el('p', {}, [gc.reason]));
      } else if (gc.code) {
        box.appendChild(el('pre', { class: 'vl-code-readout' }, [gc.code]));
      } else if (gc.error) {
        box.appendChild(el('div', { class: 'error-box' }, ['Code generation failed: ' + gc.error]));
      }
      container.appendChild(box);
    }
  }

  function renderViolationCard(v) {
    violationSeq += 1;
    const detailsId = 'vdetails-' + violationSeq;
    const techId = 'vtech-' + violationSeq;

    const catIcon = el('div', { class: 'vl-cat-icon cat-' + v.category, html: ICONS[v.category] || ICONS.data, 'aria-hidden': 'true' }, []);

    const toggleBtn = el('button', {
      type: 'button', class: 'vl-details-toggle', 'aria-expanded': 'false', 'aria-controls': detailsId,
    }, ['View details']);

    const head = el('div', { class: 'vl-card-head' }, [
      catIcon,
      el('div', { class: 'vl-card-main' }, [
        el('div', { class: 'vl-card-tags' }, [
          el('span', { class: 'vl-cat-label' }, [v.category_label]),
          el('span', { class: 'vl-sev-badge sev-' + v.severity }, [v.severity]),
        ]),
        el('div', { class: 'vl-card-sentence' }, [v.layer1_summary]),
      ]),
      toggleBtn,
    ]);

    const loc = (v.layer2 && v.layer2.location) || {};
    const locChips = [];
    if (loc.step != null) locChips.push(el('span', { class: 'vl-loc-chip' }, ['Step ' + loc.step]));
    if (loc.reagent) locChips.push(el('span', { class: 'vl-loc-chip' }, [loc.reagent]));
    if (loc.container_well) locChips.push(el('span', { class: 'vl-loc-chip' }, ['Well ' + loc.container_well]));
    if (loc.code_line) locChips.push(el('span', { class: 'vl-loc-chip' }, ['Generated code, line ' + loc.code_line]));

    const details = el('div', { id: detailsId, class: 'vl-card-details', hidden: 'hidden' }, [
      el('div', { class: 'vl-detail-block' }, [
        el('div', { class: 'vl-detail-label' }, ['Exact location']),
        el('div', { class: 'vl-detail-body' }, locChips.length ? locChips : ['No structured location data was available for this item.']),
      ]),
      el('div', { class: 'vl-detail-block' }, [
        el('div', { class: 'vl-detail-label' }, ["What's happening, in numbers"]),
        el('div', { class: 'vl-detail-body' }, [(v.layer2 && v.layer2.numbers) || v.message]),
      ]),
      el('div', { class: 'vl-detail-block' }, [
        el('div', { class: 'vl-detail-label' }, ['What could go wrong']),
        el('div', { class: 'vl-detail-body' }, [v.layer2 && v.layer2.risk]),
      ]),
      el('div', { class: 'vl-detail-block' }, [
        el('div', { class: 'vl-detail-label' }, ['Recommended corrected instruction']),
        el('div', { class: 'vl-fix-box' }, [v.layer2 && v.layer2.recommended_fix]),
      ]),
    ]);

    const techToggle = el('button', {
      type: 'button', class: 'vl-tech-toggle', 'aria-expanded': 'false', 'aria-controls': techId,
    }, ['Show technical detail']);

    const l3 = v.layer3 || {};
    const techLines = [];
    techLines.push('# extracted step (raw)');
    techLines.push(l3.extracted_step ? JSON.stringify(l3.extracted_step, null, 2) : 'null  (no structured step data for this input)');
    techLines.push('');
    techLines.push('# resolved labware capacity (raw)');
    techLines.push(l3.resolved_capacity ? JSON.stringify(l3.resolved_capacity, null, 2) : 'null  (not applicable to this finding)');
    techLines.push('');
    techLines.push('# generated code');
    if (l3.generated_code_line) {
      techLines.push('line ' + l3.generated_code_line + ': ' + (l3.generated_code_snippet || ''));
    } else {
      techLines.push('null  (no corresponding line found)');
    }
    techLines.push('');
    techLines.push('# checker output (verbatim)');
    techLines.push('code: ' + v.code);
    techLines.push('message: ' + v.message);
    techLines.push('suggested_fix: ' + (v.suggested_fix || 'null'));

    const techBlock = el('pre', { id: techId, class: 'vl-tech-block', hidden: 'hidden' }, [techLines.join('\n')]);

    details.appendChild(techToggle);
    details.appendChild(techBlock);

    toggleBtn.addEventListener('click', () => {
      const expanded = toggleBtn.getAttribute('aria-expanded') === 'true';
      toggleBtn.setAttribute('aria-expanded', String(!expanded));
      if (expanded) { details.setAttribute('hidden', 'hidden'); }
      else { details.removeAttribute('hidden'); }
      toggleBtn.textContent = expanded ? 'View details' : 'Hide details';
    });

    techToggle.addEventListener('click', () => {
      const expanded = techToggle.getAttribute('aria-expanded') === 'true';
      techToggle.setAttribute('aria-expanded', String(!expanded));
      if (expanded) { techBlock.setAttribute('hidden', 'hidden'); }
      else { techBlock.removeAttribute('hidden'); }
      techToggle.textContent = expanded ? 'Show technical detail' : 'Hide technical detail';
    });

    const sevClass = v.severity === 'error' ? 'sev-error' : 'sev-warning';
    return el('div', { class: 'vl-card ' + sevClass }, [head, details]);
  }

  return { ICONS, STAGE_ORDER, el, renderStageTracker, renderResult, renderViolationCard };
})();
