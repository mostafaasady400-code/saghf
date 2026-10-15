/**
 * سامانه هوشمند سقف - منطق فرانت‌اند و مدیریت جریان ۷ مرحله‌ای ارزیابی هوشمند ملک
 * پیاده‌سازی و کالیبراسیون بر پایه استاندارد و معماری smart.amlakmim.com
 */

(function () {
  'use strict';

  var TOTAL_STEPS = 7;

  function readRef() {
    try {
      var value = new URLSearchParams(window.location.search).get('ref');
      return value ? value.trim().slice(0, 60) : null;
    } catch (e) {
      return null;
    }
  }

  var state = {
    step: 1,
    sessionId: null,
    ref: readRef(),
    meta: null,
    otpLength: 5,
    resendCooldown: 90,
    resendTimer: null,
    statusPollTimer: null,
    data: {
      property_type: 'apartment',
      area: '',
      size_sqm: null,
      property_age: null,
      rooms: null,
      floor: null,
      total_floors: null,
      floor_units: null,
      parking_count: null,
      sanad_type: 'TAK_BARG',
      has_elevator: false,
      has_storage: false,
      has_balcony: false,
      is_renovated: false,
      is_luxury: false
    }
  };

  // ---------- ارقام و فونت فارسی ----------
  var PERSIAN = ['۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹'];

  function toFa(value) {
    return String(value).replace(/[0-9]/g, function (d) { return PERSIAN[d]; });
  }

  function toEnDigits(value) {
    return String(value)
      .replace(/[۰-۹]/g, function (d) { return String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)); })
      .replace(/[٠-٩]/g, function (d) { return String('٠١٢٣٤٥٦٧٨٩'.indexOf(d)); });
  }

  function makeFormatter(digits, least) {
    try {
      return new Intl.NumberFormat('fa-IR', {
        minimumFractionDigits: least,
        maximumFractionDigits: digits
      });
    } catch (e) {
      return null;
    }
  }

  var formatters = { 0: makeFormatter(0, 0), 1: makeFormatter(1, 0), 2: makeFormatter(2, 0) };
  var fixedFormatters = { 1: makeFormatter(1, 1), 2: makeFormatter(2, 2) };

  function faNumber(value, digits) {
    var d = digits === undefined ? 1 : digits;
    var formatter = formatters[d];
    if (formatter) return formatter.format(Number(value));
    var fixed = Number(value).toFixed(d);
    if (fixed.indexOf('.') > -1) fixed = fixed.replace(/\.?0+$/, '');
    return toFa(fixed).replace('.', '٫');
  }

  function faFixed(value, digits) {
    var formatter = fixedFormatters[digits];
    if (formatter) return formatter.format(Number(value));
    return toFa(Number(value).toFixed(digits)).replace('.', '٫');
  }

  function faGrouped(value) {
    return faNumber(Math.round(Number(value)), 0);
  }

  function $(id) { return document.getElementById(id); }

  function textSpan(text) {
    var span = document.createElement('span');
    span.textContent = text;
    return span;
  }

  var toastTimer = null;
  function toast(message, kind) {
    var el = $('toast');
    if (!el) return;
    el.textContent = message;
    el.className = 'mim-toast show' + (kind ? ' ' + kind : '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.className = 'mim-toast'; }, 4500);
  }

  function showError(id, message) {
    var el = $(id);
    if (!el) return;
    if (message) el.textContent = message;
    el.classList.add('show');
    setTimeout(function () { el.classList.remove('show'); }, 4000);
  }

  function getCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  async function api(path, options) {
    var headers = {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrfToken()
    };
    var config = Object.assign({ headers: headers }, options || {});
    config.headers = Object.assign(headers, options && options.headers ? options.headers : {});
    
    var response = await fetch(path, config);
    var payload = null;
    try { payload = await response.json(); } catch (e) { payload = null; }
    if (!response.ok) {
      var detail = (payload && (payload.detail || payload.message)) || 'خطایی در ارتباط با سرور رخ داد.';
      var error = new Error(typeof detail === 'string' ? detail : 'خطای نامشخص');
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  // ---------- مدیریت گام‌ها (Step Navigation) ----------
  function showStep(step) {
    document.querySelectorAll('.mim-step').forEach(function (node) { node.classList.remove('active'); });
    var target = document.querySelector('.mim-step[data-step="' + step + '"]');
    if (target) target.classList.add('active');

    var wrap = $('progressWrap');
    var bar = $('progressBar');
    if (step < TOTAL_STEPS) {
      wrap.style.display = 'block';
      bar.style.width = Math.round((step / TOTAL_STEPS) * 100) + '%';
    } else {
      wrap.style.display = 'none';
    }
    state.step = step;
    window.scrollTo({ top: 0, behavior: 'smooth' });
    updateScrollCue();
    setTimeout(updateScrollCue, 500);
  }

  function validateStep(step) {
    if (step === 2) {
      if (!state.data.area) {
        showError('areaError');
        $('areaInput').classList.add('error');
        setTimeout(function () { $('areaInput').classList.remove('error'); }, 2000);
        return false;
      }
      var size = numValue('size');
      var age = numValue('age');
      if (size === null || size < 20 || size > 2000) {
        showError('step2Error', 'متراژ باید بین ۲۰ تا ۲۰۰۰ متر باشد.');
        return false;
      }
      if (age === null || age < 0 || age > 100) {
        showError('step2Error', 'سن بنا باید بین ۰ تا ۱۰۰ سال باشد.');
        return false;
      }
      state.data.size_sqm = size;
      state.data.property_age = age;
      return true;
    }
    if (step === 3) {
      if (state.data.rooms === null) {
        showError('step3Error', 'تعداد خواب را انتخاب کنید.');
        return false;
      }
      if (state.data.parking_count === null) {
        showError('step3Error', 'تعداد پارکینگ را انتخاب کنید.');
        return false;
      }
      var floor = numValue('floor');
      var totalFloors = numValue('totalFloors');
      var floorUnits = numValue('floorUnits');
      if (floor === null || floor < -3 || floor > 60) {
        showError('step3Error', 'طبقه واحد را درست وارد کنید.');
        return false;
      }
      if (totalFloors === null || totalFloors < 1 || totalFloors > 60) {
        showError('step3Error', 'کل طبقات ساختمان را درست وارد کنید.');
        return false;
      }
      if (floorUnits === null || floorUnits < 1 || floorUnits > 30) {
        showError('step3Error', 'تعداد واحد در هر طبقه را درست وارد کنید.');
        return false;
      }
      if (floor > totalFloors) {
        showError('step3Error', 'طبقه واحد نمی‌تواند از کل طبقات بیشتر باشد.');
        return false;
      }
      state.data.floor = floor;
      state.data.total_floors = totalFloors;
      state.data.floor_units = floorUnits;
      return true;
    }
    return true;
  }

  async function nextStep() {
    if (!validateStep(state.step)) return;
    if (state.step === 4) {
      var sanad = sanadCombo.getValue();
      if (sanad) state.data.sanad_type = sanad;
      await createSession();
      return;
    }
    showStep(Math.min(state.step + 1, TOTAL_STEPS));
  }

  function prevStep() {
    if (state.step > 1) showStep(state.step - 1);
  }

  // ---------- فیلدهای عددی و استپرهای +/- ----------
  function numValue(id) {
    var input = $(id);
    if (!input) return null;
    var raw = toEnDigits(input.value).replace(/[^\d-]/g, '');
    if (raw === '' || raw === '-') return null;
    var parsed = parseInt(raw, 10);
    return isNaN(parsed) ? null : parsed;
  }

  function setNumValue(input, value) {
    var min = Number(input.dataset.min);
    var max = Number(input.dataset.max);
    var clamped = Math.min(max, Math.max(min, value));
    input.value = toFa(String(clamped));
  }

  function bump(input, direction) {
    var stepSize = Number(input.dataset.step) || 1;
    var current = numValue(input.id);
    if (current === null) setNumValue(input, Number(input.dataset.base));
    else setNumValue(input, current + direction * stepSize);
  }

  function setupSteppers() {
    document.querySelectorAll('.mim-stepper .mim-input').forEach(function (input) {
      var allowNegative = Number(input.dataset.min) < 0;
      input.addEventListener('input', function () {
        var raw = toEnDigits(input.value);
        var negative = allowNegative && raw.trim().charAt(0) === '-';
        var digits = raw.replace(/\D/g, '').slice(0, 4);
        input.value = digits === '' ? (negative ? '-' : '') : toFa((negative ? '-' : '') + digits);
      });
      input.addEventListener('blur', function () {
        var value = numValue(input.id);
        if (value === null) input.value = '';
        else setNumValue(input, value);
      });
      input.addEventListener('keydown', function (event) {
        if (event.key === 'Enter') { event.preventDefault(); nextStep(); }
        else if (event.key === 'ArrowUp') { event.preventDefault(); bump(input, 1); }
        else if (event.key === 'ArrowDown') { event.preventDefault(); bump(input, -1); }
      });
    });
    document.querySelectorAll('[data-stepper]').forEach(function (button) {
      button.addEventListener('click', function () {
        bump($(button.dataset.stepper), Number(button.dataset.dir));
      });
    });
  }

  // ---------- کامبوباکس و جستجوی پاپ‌اور محله و سند ----------
  function createCombo(config) {
    var root = $(config.root);
    var input = $(config.input);
    var list = $(config.list);
    var options = [];
    var selected = null;
    var query = '';
    var highlight = -1;
    var wasOpen = false;

    function normalize(text) {
      return String(text).replace(/\u200c/g, '').replace(/ي/g, 'ی').replace(/ك/g, 'ک').trim();
    }

    function visibleOptions() {
      if (!config.searchable || !query) return options;
      var needle = normalize(query);
      return options.filter(function (option) { return normalize(option.label).indexOf(needle) > -1; });
    }

    function render() {
      var items = visibleOptions();
      highlight = -1;
      list.innerHTML = '';
      if (!items.length) {
        list.innerHTML = '<div class="mim-combo-empty">' + (config.emptyText || 'موردی پیدا نشد') + '</div>';
        return;
      }
      items.forEach(function (item) {
        var node = document.createElement('div');
        node.className = 'mim-combo-option' + (selected && selected.value === item.value ? ' selected' : '');
        node.setAttribute('role', 'option');
        node.innerHTML = '<span>' + item.label + '</span>' + (item.count ? '<span style="font-size:0.75rem;color:#94a3b8;margin-right:auto;">' + toFa(item.count) + ' آگهی</span>' : '');
        node.addEventListener('mousedown', function (event) {
          event.preventDefault();
          pick(item);
        });
        list.appendChild(node);
      });
    }

    var MAX_LIST_HEIGHT = 220;
    var MARGIN = 12;

    function position() {
      var rect = input.getBoundingClientRect();
      var below = window.innerHeight - rect.bottom - MARGIN;
      var above = rect.top - MARGIN;
      var up = below < Math.min(MAX_LIST_HEIGHT, above) && above > below;
      root.classList.toggle('drop-up', up);
      list.style.maxHeight = Math.max(120, Math.min(MAX_LIST_HEIGHT, up ? above : below)) + 'px';
    }

    function open() {
      render();
      root.classList.add('open');
      input.setAttribute('aria-expanded', 'true');
      position();
      window.addEventListener('resize', position);
      window.addEventListener('scroll', position, true);
    }

    function close() {
      root.classList.remove('open');
      root.classList.remove('drop-up');
      input.setAttribute('aria-expanded', 'false');
      window.removeEventListener('resize', position);
      window.removeEventListener('scroll', position, true);
    }

    function pick(item) {
      selected = item;
      query = '';
      input.value = item.label;
      input.classList.remove('error');
      close();
      if (config.onSelect) config.onSelect(item);
    }

    function moveHighlight(delta) {
      var nodes = list.querySelectorAll('.mim-combo-option');
      if (!nodes.length) return;
      nodes.forEach(function (node) { node.classList.remove('highlight'); });
      highlight = (highlight + delta + nodes.length) % nodes.length;
      nodes[highlight].classList.add('highlight');
      nodes[highlight].scrollIntoView({ block: 'nearest' });
    }

    input.addEventListener('focus', function () {
      query = '';
      if (config.searchable && selected) input.value = '';
      if (!root.classList.contains('open')) open();
    });
    input.addEventListener('blur', function () {
      setTimeout(function () {
        close();
        if (config.searchable) input.value = selected ? selected.label : '';
      }, 140);
    });
    if (config.searchable) {
      input.addEventListener('input', function () {
        query = input.value;
        selected = null;
        if (config.onClear) config.onClear();
        open();
      });
    } else {
      input.addEventListener('mousedown', function () {
        wasOpen = root.classList.contains('open');
      });
      input.addEventListener('click', function () {
        if (wasOpen) close(); else open();
      });
    }
    input.addEventListener('keydown', function (event) {
      var items = visibleOptions();
      if (event.key === 'ArrowDown') { event.preventDefault(); if (!root.classList.contains('open')) open(); moveHighlight(1); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); moveHighlight(-1); }
      else if (event.key === 'Enter' || (!config.searchable && event.key === ' ')) {
        event.preventDefault();
        if (!root.classList.contains('open')) { open(); return; }
        if (highlight >= 0 && items[highlight]) pick(items[highlight]);
        else if (config.searchable && items.length === 1) pick(items[0]);
      } else if (event.key === 'Escape') {
        close();
      }
    });

    return {
      setOptions: function (items, defaultValue) {
        options = items || [];
        selected = null;
        input.value = '';
        if (defaultValue) {
          options.forEach(function (option) {
            if (option.value === defaultValue) pick(option);
          });
        }
      },
      getValue: function () { return selected ? selected.value : null; },
      markInvalid: function () {
        input.classList.add('error');
        setTimeout(function () { input.classList.remove('error'); }, 2000);
      }
    };
  }

  var areaCombo = null;
  var sanadCombo = null;
  var intentCombo = null;

  // ---------- بارگذاری اطلاعات اولیه (Meta API) ----------
  async function loadMeta() {
    var meta = await api('/properties/api/valuation/meta');
    state.meta = meta;
    state.otpLength = meta.otp_length || 5;
    state.resendCooldown = meta.otp_resend_cooldown || 90;
    if ($('brandName') && meta.brand_name) $('brandName').textContent = meta.brand_name;

    renderTypes(meta.property_types);
    areaCombo.setOptions(meta.areas, null);
    state.data.area = '';
    sanadCombo.setOptions(meta.sanad_types, state.data.sanad_type);
    intentCombo.setOptions(meta.intents, 'owner_sell');
    buildOtpBoxes(state.otpLength);
  }

  var TYPE_ICONS = {
    apartment: '<path d="M3 21h18"/><path d="M5 21V7l8-4v18"/><path d="M19 21V11l-6-4"/><path d="M9 9h.01"/><path d="M9 12h.01"/><path d="M9 15h.01"/><path d="M9 18h.01"/>',
    office: '<path d="M3 21h18"/><path d="M5 21V4a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v17"/><path d="M8 7h3"/><path d="M13 7h3"/><path d="M8 11h3"/><path d="M13 11h3"/><path d="M10 21v-4h4v4"/>',
    commercial: '<path d="M3 21h18"/><path d="M5 21V11h14v10"/><path d="M4 11h16l-1.5-4.5h-13z"/><path d="M9.5 21v-5h5v5"/>',
    mostaghalat: '<path d="M2 21h20"/><path d="M4 21v-7.5h4.5V21"/><path d="M9.5 21V6.5h5V21"/><path d="M15.5 21v-5.5H20V21"/><path d="M6.2 17h.01"/><path d="M11.9 10h.01"/><path d="M11.9 14h.01"/><path d="M17.7 18h.01"/>',
    kolangi: '<path d="M3 21h18"/><path d="M5 21V5l7-3 7 3v16"/><path d="M9 21v-6h6v6"/><path d="M9 9h6"/>',
    land: '<path d="M3 20h18"/><path d="M4 20V8l8-4 8 4v12"/><path d="M4 12h16"/><path d="M12 4v16"/>'
  };

  function renderTypes(types) {
    var grid = $('typeGrid');
    if (!grid) return;
    grid.innerHTML = '';
    types.forEach(function (type) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'mim-type-card' + (type.enabled ? '' : ' disabled') + (type.value === state.data.property_type ? ' selected' : '');
      button.dataset.type = type.value;
      button.innerHTML =
        (type.enabled ? '' : '<span class="mim-soon-badge">به‌زودی</span>') +
        '<svg viewBox="0 0 24 24">' + (TYPE_ICONS[type.value] || TYPE_ICONS.apartment) + '</svg>' +
        '<span>' + type.label + '</span>';
      if (type.enabled) {
        button.addEventListener('click', function () {
          document.querySelectorAll('.mim-type-card').forEach(function (c) { c.classList.remove('selected'); });
          button.classList.add('selected');
          state.data.property_type = type.value;
          setTimeout(function () { showStep(2); }, 250);
        });
      } else {
        button.addEventListener('click', function () {
          toast('ارزیابی ' + type.label + ' به‌زودی فعال می‌شود.', 'info');
        });
      }
      grid.appendChild(button);
    });
  }

  // ---------- ایجاد سشن در بک‌اند ----------
  async function createSession() {
    var button = $('finishFormBtn');
    button.disabled = true;
    button.innerHTML = '<div class="mim-spinner"></div> در حال پردازش مشخصات...';
    try {
      var body = Object.assign({}, state.data);
      if (state.ref) body.ref = state.ref;
      var result = await api('/properties/api/valuation/sessions', {
        method: 'POST',
        body: JSON.stringify(body)
      });
      state.sessionId = result.session_id;
      showStep(5);
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      button.disabled = false;
      button.innerHTML = 'انجام ارزیابی <svg viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6"/></svg>';
    }
  }

  // ---------- سیستم ارسال و تایید کد پیامکی (OTP) ----------
  function buildOtpBoxes(length) {
    var wrap = $('otpInputs');
    if (!wrap) return;
    wrap.innerHTML = '';
    for (var i = 0; i < length; i++) {
      var box = document.createElement('input');
      box.type = 'text';
      box.className = 'mim-otp-box';
      box.maxLength = 1;
      box.inputMode = 'numeric';
      box.autocomplete = i === 0 ? 'one-time-code' : 'off';
      box.dataset.index = String(i);
      box.dataset.digit = '';
      wrap.appendChild(box);
    }

    function fillAll(text) {
      for (var i = 0; i < length; i++) {
        var target = wrap.children[i];
        if (target) {
          target.dataset.digit = text[i] || '';
          target.value = text[i] ? toFa(text[i]) : '';
          target.classList.toggle('filled', Boolean(text[i]));
        }
      }
      if (text.length >= length) verifyOtp();
    }

    wrap.querySelectorAll('.mim-otp-box').forEach(function (box) {
      box.addEventListener('input', function () {
        var digits = toEnDigits(box.value).replace(/\D/g, '');
        if (digits.length > 1) {
          fillAll(digits.slice(0, length));
          return;
        }
        box.dataset.digit = digits;
        box.value = digits ? toFa(digits) : '';
        box.classList.toggle('filled', digits !== '');
        var index = Number(box.dataset.index);
        if (digits && index < length - 1) wrap.children[index + 1].focus();
        if (readOtp().length === length) verifyOtp();
      });
      box.addEventListener('keydown', function (event) {
        var index = Number(box.dataset.index);
        if (event.key === 'Backspace' && !box.value && index > 0) wrap.children[index - 1].focus();
        if (event.key === 'ArrowLeft' && index < length - 1) wrap.children[index + 1].focus();
        if (event.key === 'ArrowRight' && index > 0) wrap.children[index - 1].focus();
      });
      box.addEventListener('paste', function (event) {
        event.preventDefault();
        var text = toEnDigits((event.clipboardData || window.clipboardData).getData('text')).replace(/\D/g, '');
        fillAll(text.slice(0, length));
      });
    });
  }

  function readOtp() {
    return Array.prototype.map.call($('otpInputs').children, function (box) {
      return box.dataset.digit || '';
    }).join('');
  }

  function clearOtp() {
    Array.prototype.forEach.call($('otpInputs').children, function (box) {
      box.value = '';
      box.dataset.digit = '';
      box.classList.remove('filled');
    });
    if ($('otpInputs').children[0]) $('otpInputs').children[0].focus();
  }

  function startResendTimer(seconds) {
    clearInterval(state.resendTimer);
    var remaining = seconds;
    var timerWrap = $('otpTimerWrap');
    var resend = $('resendBtn');
    resend.disabled = true;
    timerWrap.style.display = 'inline';

    function tick() {
      if (remaining <= 0) {
        clearInterval(state.resendTimer);
        timerWrap.style.display = 'none';
        resend.disabled = false;
        return;
      }
      var minutes = Math.floor(remaining / 60);
      var secs = remaining % 60;
      $('otpTimer').textContent = toFa(String(minutes).padStart(2, '0') + ':' + String(secs).padStart(2, '0'));
      remaining -= 1;
    }
    tick();
    state.resendTimer = setInterval(tick, 1000);
  }

  function startStatusPolling(sessionId) {
    if (state.statusPollTimer) clearInterval(state.statusPollTimer);
    if ($('tgStatusText')) $('tgStatusText').textContent = 'در حال گوش دادن به تایید آنی از تلگرام...';

    state.statusPollTimer = setInterval(async function () {
      if (state.step !== 6 || !sessionId) {
        clearInterval(state.statusPollTimer);
        return;
      }
      try {
        var statusData = await api('/properties/api/valuation/sessions/' + sessionId + '/status');
        if (statusData && statusData.is_verified) {
          clearInterval(state.statusPollTimer);
          clearInterval(state.resendTimer);
          if ($('tgStatusText')) $('tgStatusText').textContent = '✅ تایید شد! در حال دریافت گزارش ارزیابی...';
          toast('سشن ارزیابی از طریق تلگرام با موفقیت تایید شد!', 'success');
          var result = await api('/properties/api/valuation/sessions/' + sessionId + '/result');
          renderResult(result);
          showStep(7);
          setTimeout(animateResult, 250);
        }
      } catch (e) {
        // Silent poll error
      }
    }, 2500);
  }

  async function sendOtp(isResend) {
    var phoneInput = $('phone');
    var phone = toEnDigits(phoneInput.value).replace(/\D/g, '');
    if (!/^09\d{9}$/.test(phone)) {
      phoneInput.classList.add('error');
      showError('phoneError', 'شماره موبایل را به صورت ۰۹۱۲۱۲۳۴۵۶۷ وارد کنید.');
      setTimeout(function () { phoneInput.classList.remove('error'); }, 2000);
      return;
    }
    var intent = intentCombo.getValue();
    if (!intent) {
      intentCombo.markInvalid();
      showError('intentError');
      return;
    }

    var button = isResend ? $('resendBtn') : $('sendOtpBtn');
    button.disabled = true;
    if (!isResend) button.innerHTML = '<div class="mim-spinner"></div> در حال ارسال به تلگرام...';

    try {
      var result = await api('/properties/api/valuation/sessions/' + state.sessionId + '/otp', {
        method: 'POST',
        body: JSON.stringify({ phone: phone, intent: intent, method: 'telegram' })
      });

      $('maskedPhone').textContent = toFa(result.masked_phone);
      if (result.telegram_link && $('tgBotLink')) {
        $('tgBotLink').href = result.telegram_link;
      }
      if (result.debug_code) {
        $('debugCode').style.display = 'block';
        $('debugCode').textContent = 'کد تایید ارسال‌شده به تلگرام: ' + toFa(result.debug_code);
      } else {
        $('debugCode').style.display = 'none';
      }
      clearOtp();
      showStep(6);
      startResendTimer(result.resend_after || state.resendCooldown);
      startStatusPolling(state.sessionId);
      setTimeout(function () { if ($('otpInputs').children[0]) $('otpInputs').children[0].focus(); }, 300);
    } catch (error) {
      toast(error.message, 'error');
      if (isResend) button.disabled = false;
    } finally {
      if (!isResend) {
        button.disabled = false;
        button.innerHTML = 'مشاهده ارزیابی قیمت';
      }
    }
  }

  var verifying = false;
  async function verifyOtp() {
    if (verifying) return;
    var code = readOtp();
    if (code.length !== state.otpLength) {
      showError('otpError', 'کد ' + toFa(state.otpLength) + ' رقمی را کامل وارد کنید.');
      return;
    }
    verifying = true;
    var button = $('verifyBtn');
    button.disabled = true;
    button.innerHTML = '<div class="mim-spinner"></div> در حال ارزیابی با هوش مصنوعی...';
    try {
      var result = await api('/properties/api/valuation/sessions/' + state.sessionId + '/verify', {
        method: 'POST',
        body: JSON.stringify({ code: code })
      });
      clearInterval(state.resendTimer);
      if (state.statusPollTimer) clearInterval(state.statusPollTimer);
      renderResult(result);
      showStep(7);
      setTimeout(animateResult, 250);
    } catch (error) {
      $('otpInputs').classList.add('otp-boxes-error');
      setTimeout(function () { $('otpInputs').classList.remove('otp-boxes-error'); }, 1600);
      showError('otpError', error.message);
      clearOtp();
    } finally {
      verifying = false;
      button.disabled = false;
      button.innerHTML = 'تایید و مشاهده قیمت';
    }
  }

  // ---------- رندر داشبورد نتایج و نمودارها (Result Dashboard) ----------
  var resultCache = null;

  function renderResult(result) {
    resultCache = result;
    var billion = 1e9;
    var million = 1e6;

    var chip = $('priceChip');
    chip.textContent = '';
    chip.appendChild(textSpan(result.area));
    chip.appendChild(document.createElement('i')).className = 'mim-chip-dot';
    chip.appendChild(textSpan(faNumber(result.size_sqm, 0) + ' متر'));

    $('totalAvg').textContent = faFixed(result.total.avg / billion, 2);
    $('totalMin').textContent = faFixed(result.total.min / billion, 2);
    $('totalMax').textContent = faFixed(result.total.max / billion, 2);

    $('meterAvg').innerHTML =
      faFixed(result.per_meter.avg / million, 1) + '<span class="mim-pm-unit">میلیون تومان</span>';
    $('meterRange').innerHTML =
      faFixed(result.per_meter.min / million, 1) + ' تا ' +
      faFixed(result.per_meter.max / million, 1) + '<span class="mim-pm-unit">میلیون</span>';

    $('resultSubtitle').textContent = 'بر اساس ' + toFa(result.sample_count || 12) + ' آگهی واقعی و معتبر همین محله';

    var rates = result.rates || {};
    if (rates.available && rates.equivalent_gold_grams && rates.equivalent_usd) {
      $('equivBlock').style.display = 'block';
      $('goldEquiv').textContent = faGrouped(rates.equivalent_gold_grams);
      $('usdEquiv').textContent = faGrouped(rates.equivalent_usd);
      $('goldRate').textContent = 'نرخ هر گرم: ' + faGrouped(rates.gold_rate) + ' تومان';
      $('usdRate').textContent = 'نرخ هر دلار: ' + faGrouped(rates.usd_rate) + ' تومان';
    } else {
      $('equivBlock').style.display = 'none';
    }

    renderComparables(result.comparables || []);
    updateScrollCue();
  }

  function renderComparables(items) {
    var block = $('compsBlock');
    if (!items.length) {
      block.style.display = 'none';
      return;
    }
    $('compsList').innerHTML = items.map(function (item) {
      var facts = [
        item.rooms > 0 ? toFa(item.rooms) + ' خوابه' : 'بدون خواب',
        item.property_age > 0 ? toFa(item.property_age) + ' سال ساخت' : 'نوساز',
        'طبقه ' + toFa(item.floor) + ' از ' + toFa(item.total_floors),
        item.parking_count > 0 ? toFa(item.parking_count) + ' پارکینگ' : 'بدون پارکینگ'
      ];
      if (item.has_elevator) facts.push('آسانسور');
      if (item.has_storage) facts.push('انباری');
      
      var linkHtml = item.source_url ? 
        '<a href="' + item.source_url + '" target="_blank" rel="noopener noreferrer" class="mim-comp-link">لینک آگهی مستقیم</a>' : '';

      return (
        '<div class="mim-comp-card">' +
          '<div class="mim-comp-head">' +
            '<span class="mim-comp-size">' + faNumber(item.size_sqm, 0) + ' متر</span>' +
            '<span class="mim-comp-price">' + faNumber(item.total_price / 1e9, 2) + ' میلیارد تومان</span>' +
          '</div>' +
          '<div class="mim-comp-meta">' +
            facts.map(function (text) { return '<span>' + text + '</span>'; }).join('') +
          '</div>' +
          '<div class="mim-comp-foot">' +
            '<span>هر متر ' + faGrouped(item.price_per_meter) + ' تومان · تاریخ ثبت ' + toFa(item.ad_date_fa || '۱۴۰۵') + '</span>' +
            linkHtml +
          '</div>' +
        '</div>'
      );
    }).join('');
    block.style.display = 'block';
  }

  function updateScrollCue() {
    var cue = $('scrollCue');
    if (!cue) return;
    var room = document.documentElement.scrollHeight - window.innerHeight;
    var atBottom = window.scrollY >= room - 30;
    cue.classList.toggle('on', state.step === TOTAL_STEPS && room > 40 && !atBottom);
  }

  function animateResult() {
    if (!resultCache) return;
    animateNumber('totalAvg', resultCache.total.avg / 1e9, 2);
    setTimeout(function () { if ($('priceBarFill')) $('priceBarFill').style.width = '100%'; }, 150);
    setTimeout(function () { if ($('priceBarDot')) $('priceBarDot').classList.add('show'); }, 150);
  }

  function animateNumber(id, end, digits) {
    var el = $(id);
    if (!el) return;
    var duration = 1200;
    var start = performance.now();
    function tick(now) {
      var progress = Math.min((now - start) / duration, 1);
      var eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = faFixed(end * eased, digits);
      if (progress < 1) requestAnimationFrame(tick);
      else el.textContent = faFixed(end, digits);
    }
    requestAnimationFrame(tick);
  }

  // ---------- درخواست کارشناسی رایگان و دقیق حضوری ----------
  var EXPERT_LABEL =
    '<svg viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>' +
    '<circle cx="12" cy="7" r="4"/></svg> درخواست کارشناسی رایگان و دقیق';

  function expertButtons() { return document.querySelectorAll('[data-expert]'); }

  async function requestExpert(event) {
    var pressed = event.currentTarget;
    expertButtons().forEach(function (button) {
      button.disabled = true;
      button.innerHTML = button === pressed
        ? '<div class="mim-spinner"></div> در حال ثبت درخواست...'
        : EXPERT_LABEL;
    });

    try {
      var result = await api('/properties/api/valuation/sessions/' + state.sessionId + '/expert-request', {
        method: 'POST',
        body: JSON.stringify({ note: 'درخواست کارشناسی ثبت‌شده از وب‌سایت' })
      });
      expertButtons().forEach(function (button) { button.style.display = 'none'; });
      document.querySelectorAll('.mim-expert-done').forEach(function (note) {
        note.classList.add('show');
      });
      toast(result.message, 'success');
    } catch (error) {
      toast(error.message, 'error');
      expertButtons().forEach(function (button) {
        button.disabled = false;
        button.innerHTML = EXPERT_LABEL;
      });
    }
  }

  // ---------- راه‌اندازی رویدادها (Event Listeners) ----------
  function setupEvents() {
    document.querySelectorAll('[data-next]').forEach(function (button) {
      button.addEventListener('click', nextStep);
    });
    document.querySelectorAll('[data-prev]').forEach(function (button) {
      button.addEventListener('click', prevStep);
    });
    document.querySelectorAll('[data-choice]').forEach(function (row) {
      var key = row.dataset.choice === 'rooms' ? 'rooms' : 'parking_count';
      row.querySelectorAll('.mim-choice-btn').forEach(function (button) {
        button.addEventListener('click', function () {
          row.querySelectorAll('.mim-choice-btn').forEach(function (b) { b.classList.remove('selected'); });
          button.classList.add('selected');
          state.data[key] = Number(button.dataset.val);
        });
      });
    });
    document.querySelectorAll('[data-fac]').forEach(function (button) {
      button.addEventListener('click', function () {
        button.classList.toggle('active');
        state.data[button.dataset.fac] = button.classList.contains('active');
      });
    });

    var finishBtn = $('finishFormBtn');
    if (finishBtn) finishBtn.addEventListener('click', nextStep);

    var sendOtpBtn = $('sendOtpBtn');
    if (sendOtpBtn) sendOtpBtn.addEventListener('click', function () { sendOtp(false); });

    var resendBtn = $('resendBtn');
    if (resendBtn) resendBtn.addEventListener('click', function () { sendOtp(true); });

    var verifyBtn = $('verifyBtn');
    if (verifyBtn) verifyBtn.addEventListener('click', verifyOtp);

    var changePhoneBtn = $('changePhoneBtn');
    if (changePhoneBtn) changePhoneBtn.addEventListener('click', function () {
      clearInterval(state.resendTimer);
      if (state.statusPollTimer) clearInterval(state.statusPollTimer);
      showStep(5);
    });

    expertButtons().forEach(function (button) {
      button.addEventListener('click', requestExpert);
    });

    var phoneInput = $('phone');
    if (phoneInput) {
      phoneInput.addEventListener('input', function () {
        this.value = toFa(toEnDigits(this.value).replace(/\D/g, '').slice(0, 11));
      });
      phoneInput.addEventListener('keydown', function (event) {
        if (event.key === 'Enter') { event.preventDefault(); sendOtp(false); }
      });
    }

    window.addEventListener('scroll', updateScrollCue, { passive: true });
    window.addEventListener('resize', updateScrollCue);
  }

  document.addEventListener('DOMContentLoaded', function () {
    areaCombo = createCombo({
      root: 'areaCombo',
      input: 'areaInput',
      list: 'areaList',
      searchable: true,
      emptyText: 'محله‌ای پیدا نشد',
      onSelect: function (item) {
        state.data.area = item.value;
      },
      onClear: function () { state.data.area = ''; }
    });
    sanadCombo = createCombo({ root: 'sanadCombo', input: 'sanadInput', list: 'sanadList' });
    intentCombo = createCombo({ root: 'intentCombo', input: 'intentInput', list: 'intentList' });

    setupSteppers();
    setupEvents();
    loadMeta().catch(function (error) {
      toast('بارگذاری اطلاعات ناموفق بود: ' + error.message, 'error');
    });

    // تایید خودکار در صورت باز شدن صفحه از طریق لینک بات تلگرام
    var card = $('mimCard');
    var urlParams = new URLSearchParams(window.location.search);
    var autoSession = (card && card.dataset.autoSession) || urlParams.get('session_id');
    var autoCode = (card && card.dataset.autoCode) || urlParams.get('verify_code');
    if (autoSession && autoCode) {
      state.sessionId = autoSession;
      toast('در حال تایید خودکار سشن از طریق تلگرام...', 'info');
      api('/properties/api/valuation/sessions/' + autoSession + '/verify', {
        method: 'POST',
        body: JSON.stringify({ code: autoCode })
      }).then(function (result) {
        toast('تایید سشن با موفقیت انجام شد!', 'success');
        renderResult(result);
        showStep(7);
        setTimeout(animateResult, 250);
      }).catch(function (err) {
        toast('خطا در تایید سشن: ' + err.message, 'error');
      });
    }
  });
})();
