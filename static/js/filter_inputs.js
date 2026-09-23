/**
 * filter_inputs.js - مدیریت هوشمند فیلترهای قیمتی و سن بنا در سامانه سقف
 */

(function () {
    'use strict';

    const ONES = ['', 'یک', 'دو', 'سه', 'چهار', 'پنج', 'شش', 'هفت', 'هشت', 'نه'];
    const TEENS = ['ده', 'یازده', 'دوازده', 'سیزده', 'چهارده', 'پانزده', 'شانزده', 'هفده', 'هجده', 'نوزده'];
    const TENS = ['', '', 'بیست', 'سی', 'چهل', 'پنجاه', 'شصت', 'هفتاد', 'هشتاد', 'نود'];
    const HUNDREDS = ['', 'صد', 'دویست', 'سیصد', 'چهارصد', 'پانصد', 'ششصد', 'هفتصد', 'هشتصد', 'نهصد'];
    const SCALES = ['', 'هزار', 'میلیون', 'میلیارد', 'همت'];

    function persianDigits(str) {
        if (str === null || str === undefined) return '';
        const fa = ['۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹'];
        return String(str).replace(/[0-9]/g, function(w) { return fa[+w]; });
    }

    function englishDigits(str) {
        if (!str) return '';
        const fa = '۰۱۲۳۴۵۶۷۸۹';
        const ar = '٠١٢٣٤٥٦٧٨٩';
        let res = String(str);
        for (let i = 0; i < 10; i++) {
            res = res.split(fa[i]).join(String(i)).split(ar[i]).join(String(i));
        }
        return res.replace(/[^\d]/g, '');
    }

    function formatNumberCommas(num) {
        const clean = englishDigits(num);
        if (!clean) return '';
        return clean.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    }

    function convertGroupToWords(n) {
        let parts = [];
        const h = Math.floor(n / 100);
        const rem = n % 100;
        if (h > 0) parts.push(HUNDREDS[h]);

        if (rem >= 10 && rem <= 19) {
            parts.push(TEENS[rem - 10]);
        } else {
            const t = Math.floor(rem / 10);
            const o = rem % 10;
            if (t > 0) parts.push(TENS[t]);
            if (o > 0) parts.push(ONES[o]);
        }
        return parts.join(' و ');
    }

    function numberToPersianWords(num) {
        const raw = parseInt(englishDigits(num), 10);
        if (isNaN(raw) || raw <= 0) return '';
        if (raw === 0) return 'صفر تومان';

        let n = raw;
        let groups = [];
        while (n > 0) {
            groups.push(n % 1000);
            n = Math.floor(n / 1000);
        }

        let wordsParts = [];
        for (let i = groups.length - 1; i >= 0; i--) {
            const g = groups[i];
            if (g > 0) {
                const groupStr = convertGroupToWords(g);
                const scale = SCALES[i];
                wordsParts.push(scale ? (groupStr + ' ' + scale) : groupStr);
            }
        }

        return wordsParts.length > 0 ? (wordsParts.join(' و ') + ' تومان') : '';
    }

    const QUICK_AMOUNTS = {
        deposit: [
            { label: '۱۰۰ میلیون', value: 100000000 },
            { label: '۲۰۰ میلیون', value: 200000000 },
            { label: '۳۰۰ میلیون', value: 300000000 },
            { label: '۵۰۰ میلیون', value: 500000000 },
            { label: '۸۰۰ میلیون', value: 800000000 },
            { label: '۱ میلیارد', value: 1000000000 },
            { label: '۱.۵ میلیارد', value: 1500000000 },
            { label: '۲ میلیارد', value: 2000000000 },
            { label: '۳ میلیارد', value: 3000000000 },
            { label: '۵ میلیارد', value: 5000000000 }
        ],
        rent: [
            { label: '۵ میلیون', value: 5000000 },
            { label: '۱۰ میلیون', value: 10000000 },
            { label: '۱۵ میلیون', value: 15000000 },
            { label: '۲۰ میلیون', value: 20000000 },
            { label: '۲۵ میلیون', value: 25000000 },
            { label: '۳۵ میلیون', value: 35000000 },
            { label: '۵۰ میلیون', value: 50000000 },
            { label: '۷۰ میلیون', value: 70000000 },
            { label: '۱۰۰ میلیون', value: 100000000 }
        ],
        price: [
            { label: '۲ میلیارد', value: 2000000000 },
            { label: '۳ میلیارد', value: 3000000000 },
            { label: '۵ میلیارد', value: 5000000000 },
            { label: '۷ میلیارد', value: 7000000000 },
            { label: '۱۰ میلیارد', value: 10000000000 },
            { label: '۱۵ میلیارد', value: 15000000000 },
            { label: '۲۰ میلیارد', value: 20000000000 },
            { label: '۳۰ میلیارد', value: 30000000000 },
            { label: '۵۰ میلیارد', value: 50000000000 }
        ]
    };

    function attachSmartFinancialInput(inputEl, type) {
        if (!inputEl) return;
        type = type || 'price';

        const parent = inputEl.parentElement;
        if (!parent) return;

        const fieldName = inputEl.getAttribute('name');
        const initialVal = inputEl.value;

        let hiddenInput = parent.querySelector('input[type="hidden"][name="' + fieldName + '"]');
        if (!hiddenInput && fieldName) {
            hiddenInput = document.createElement('input');
            hiddenInput.type = 'hidden';
            hiddenInput.name = fieldName;
            hiddenInput.value = englishDigits(initialVal);
            parent.appendChild(hiddenInput);
        }

        inputEl.type = 'text';
        inputEl.removeAttribute('name');
        inputEl.classList.add('smart-price-input');
        inputEl.autocomplete = 'off';

        if (initialVal) {
            inputEl.value = persianDigits(formatNumberCommas(initialVal));
        }

        let wordsLabel = parent.querySelector('.price-words-label');
        if (!wordsLabel) {
            wordsLabel = document.createElement('div');
            wordsLabel.className = 'price-words-label';
            wordsLabel.style.cssText = 'font-size: 0.74rem; color: #38bdf8; margin-top: 0.35rem; min-height: 1.25rem; line-height: 1.25rem; font-weight: 600; transition: all 0.2s ease; word-break: break-word;';
            parent.appendChild(wordsLabel);
        }

        if (initialVal) {
            const words = numberToPersianWords(initialVal);
            wordsLabel.textContent = words ? ('« ' + words + ' »') : '';
        }

        let chipsDropdown = parent.querySelector('.quick-chips-dropdown');
        if (!chipsDropdown) {
            chipsDropdown = document.createElement('div');
            chipsDropdown.className = 'quick-chips-dropdown glass-card';
            chipsDropdown.style.cssText = 'display: none; position: absolute; top: 100%; right: 0; left: 0; z-index: 50; background: rgba(15, 23, 42, 0.97); backdrop-filter: blur(14px); border: 1px solid rgba(56, 189, 248, 0.35); border-radius: 10px; padding: 0.6rem; margin-top: 0.3rem; box-shadow: 0 10px 25px rgba(0, 0, 0, 0.6); max-height: 175px; overflow-y: auto;';

            const chipsTitle = document.createElement('div');
            chipsTitle.style.cssText = 'font-size: 0.72rem; color: #94a3b8; margin-bottom: 0.4rem; font-weight: 600; display: flex; justify-content: space-between; align-items: center;';
            chipsTitle.innerHTML = '<span>⚡ مبالغ پیشنهادی آماده:</span> <span style="font-size: 0.68rem; color: #64748b; cursor: pointer;">✕ بستن</span>';
            chipsDropdown.appendChild(chipsTitle);

            const closeBtn = chipsTitle.querySelector('span:last-child');
            if (closeBtn) {
                closeBtn.addEventListener('click', function(e) {
                    e.stopPropagation();
                    chipsDropdown.style.display = 'none';
                });
            }

            const chipsGrid = document.createElement('div');
            chipsGrid.style.cssText = 'display: flex; flex-wrap: wrap; gap: 0.35rem;';

            const items = QUICK_AMOUNTS[type] || QUICK_AMOUNTS.price;
            items.forEach(function(item) {
                const chip = document.createElement('button');
                chip.type = 'button';
                chip.className = 'quick-select-chip';
                chip.style.cssText = 'background: rgba(56, 189, 248, 0.1); border: 1px solid rgba(56, 189, 248, 0.25); color: #e0f2fe; padding: 0.25rem 0.55rem; border-radius: 6px; font-size: 0.74rem; cursor: pointer; transition: all 0.15s ease;';
                chip.textContent = item.label;

                chip.addEventListener('mouseenter', function() {
                    chip.style.background = 'rgba(56, 189, 248, 0.25)';
                    chip.style.borderColor = '#38bdf8';
                });
                chip.addEventListener('mouseleave', function() {
                    chip.style.background = 'rgba(56, 189, 248, 0.1)';
                    chip.style.borderColor = 'rgba(56, 189, 248, 0.25)';
                });

                chip.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    if (hiddenInput) hiddenInput.value = item.value;
                    inputEl.value = persianDigits(formatNumberCommas(item.value));
                    wordsLabel.textContent = '« ' + numberToPersianWords(item.value) + ' »';
                    chipsDropdown.style.display = 'none';
                    inputEl.dispatchEvent(new Event('change', { bubbles: true }));
                });

                chipsGrid.appendChild(chip);
            });

            chipsDropdown.appendChild(chipsGrid);
            parent.style.position = 'relative';
            parent.appendChild(chipsDropdown);
        }

        inputEl.addEventListener('input', function () {
            const rawVal = englishDigits(this.value);
            if (hiddenInput) hiddenInput.value = rawVal;

            if (!rawVal) {
                this.value = '';
                wordsLabel.textContent = '';
                return;
            }

            const formatted = formatNumberCommas(rawVal);
            this.value = persianDigits(formatted);

            const words = numberToPersianWords(rawVal);
            wordsLabel.textContent = words ? ('« ' + words + ' »') : '';
        });

        inputEl.addEventListener('focus', function () {
            if (chipsDropdown) chipsDropdown.style.display = 'block';
        });

        document.addEventListener('click', function (e) {
            if (!parent.contains(e.target)) {
                if (chipsDropdown) chipsDropdown.style.display = 'none';
            }
        });
    }

    function initAllSmartFilters() {
        attachSmartFinancialInput(document.getElementById('filterMinPrice'), 'price');
        attachSmartFinancialInput(document.getElementById('filterMaxPrice'), 'price');
        attachSmartFinancialInput(document.getElementById('filterMinDeposit'), 'deposit');
        attachSmartFinancialInput(document.getElementById('filterMaxDeposit'), 'deposit');
        attachSmartFinancialInput(document.getElementById('filterMinRent'), 'rent');
        attachSmartFinancialInput(document.getElementById('filterMaxRent'), 'rent');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAllSmartFilters);
    } else {
        initAllSmartFilters();
    }

    window.SaghfFilterInputs = {
        numberToPersianWords: numberToPersianWords,
        formatNumberCommas: formatNumberCommas,
        attachSmartFinancialInput: attachSmartFinancialInput,
        initAllSmartFilters: initAllSmartFilters
    };
})();