/**
 * district_picker.js - سیستم مدرن انتخاب محله و منطقه با جستجوی زنده و اسکرول نرم نامحدود
 * برای سامانه املاک سقف
 */

(function () {
    'use strict';

    function initDistrictPicker() {
        const pickerTrigger = document.getElementById('districtPickerTrigger');
        const pickerDropdown = document.getElementById('districtPickerDropdown');
        const searchInput = document.getElementById('districtPickerSearch');
        const listContainer = document.getElementById('districtPickerList');
        const hiddenInput = document.getElementById('filterDistrict');
        const selectedLabel = document.getElementById('districtPickerSelectedLabel');
        const clearBtn = document.getElementById('districtPickerClearBtn');

        if (!pickerTrigger || !pickerDropdown || !hiddenInput || !listContainer) return;

        // استخراج کلیه آیتم‌های محله از دیتا ویژگی‌های صفحه یا آرایه عمومی
        let allDistricts = [];
        if (window.__TEHRAN_DISTRICTS_DATA__ && window.__TEHRAN_DISTRICTS_DATA__.length > 0) {
            const rawData = window.__TEHRAN_DISTRICTS_DATA__;
            if (rawData[0] && (rawData[0].districts || rawData[0].sub_districts)) {
                rawData.forEach(function(reg) {
                    const regName = reg.name || ('منطقه ' + reg.id);
                    const subList = reg.districts || reg.sub_districts || [];
                    subList.forEach(function(d) {
                        const dName = typeof d === 'string' ? d : d.name;
                        if (dName) {
                            allDistricts.push({
                                name: dName,
                                region: regName
                            });
                        }
                    });
                });
            } else {
                allDistricts = rawData;
            }
        } else {
            // استخراج از آپشن‌های قبلی سلکت در صورت وجود
            const existingSelect = document.getElementById('legacyDistrictSelect');
            if (existingSelect) {
                const optgroups = existingSelect.querySelectorAll('optgroup');
                if (optgroups.length > 0) {
                    optgroups.forEach(function(og) {
                        const regionName = og.label;
                        og.querySelectorAll('option').forEach(function(opt) {
                            if (opt.value && opt.value !== 'all') {
                                allDistricts.push({
                                    name: opt.value,
                                    region: regionName
                                });
                            }
                        });
                    });
                } else {
                    existingSelect.querySelectorAll('option').forEach(function(opt) {
                        if (opt.value && opt.value !== 'all') {
                            allDistricts.push({
                                name: opt.value,
                                region: 'تهران'
                            });
                        }
                    });
                }
            }
        }

        let filteredDistricts = allDistricts.slice();
        let renderedCount = 0;
        const BATCH_SIZE = 12;

        function renderNextBatch() {
            if (renderedCount >= filteredDistricts.length) return;

            const nextBatch = filteredDistricts.slice(renderedCount, renderedCount + BATCH_SIZE);
            const currentSelected = hiddenInput.value;

            nextBatch.forEach(function(item) {
                const itemEl = document.createElement('div');
                itemEl.className = 'district-picker-item' + (currentSelected === item.name ? ' active-selected' : '');
                itemEl.style.cssText = 'padding: 0.55rem 0.85rem; border-radius: 8px; margin-bottom: 0.25rem; display: flex; justify-content: space-between; align-items: center; cursor: pointer; transition: all 0.15s ease; font-size: 0.83rem;';

                if (currentSelected === item.name) {
                    itemEl.style.background = 'rgba(0, 242, 254, 0.18)';
                    itemEl.style.color = '#00f2fe';
                    itemEl.style.fontWeight = '700';
                } else {
                    itemEl.style.color = '#e2e8f0';
                }

                itemEl.innerHTML = '<span>' + item.name + '</span> <span style="font-size: 0.72rem; color: #64748b; background: rgba(255,255,255,0.05); padding: 0.1rem 0.4rem; border-radius: 4px;">' + (item.region || 'تهران') + '</span>';

                itemEl.addEventListener('mouseenter', function() {
                    if (hiddenInput.value !== item.name) {
                        itemEl.style.background = 'rgba(255, 255, 255, 0.08)';
                    }
                });
                itemEl.addEventListener('mouseleave', function() {
                    if (hiddenInput.value !== item.name) {
                        itemEl.style.background = 'transparent';
                    }
                });

                itemEl.addEventListener('click', function() {
                    selectDistrict(item.name);
                });

                listContainer.appendChild(itemEl);
            });

            renderedCount += nextBatch.length;
        }

        function resetAndRender(items) {
            filteredDistricts = items;
            renderedCount = 0;
            listContainer.innerHTML = '';

            if (filteredDistricts.length === 0) {
                const emptyEl = document.createElement('div');
                emptyEl.style.cssText = 'padding: 1.5rem; text-align: center; color: #94a3b8; font-size: 0.82rem;';
                emptyEl.textContent = 'محله‌ای با این نام یافت نشد.';
                listContainer.appendChild(emptyEl);
                return;
            }

            renderNextBatch();
        }

        function selectDistrict(name) {
            hiddenInput.value = name || 'all';
            if (name && name !== 'all') {
                selectedLabel.textContent = name;
                if (clearBtn) clearBtn.style.display = 'inline-flex';
                pickerTrigger.classList.add('has-selection');
            } else {
                selectedLabel.textContent = 'همه مناطق و محله‌ها';
                if (clearBtn) clearBtn.style.display = 'none';
                pickerTrigger.classList.remove('has-selection');
            }
            closePicker();

            // در صورتی که نیاز به سابمیت یا تغییر باشد
            hiddenInput.dispatchEvent(new Event('change', { bubbles: true }));
        }

        function openPicker() {
            pickerDropdown.style.display = 'block';
            pickerTrigger.classList.add('picker-opened');
            if (searchInput) {
                searchInput.value = '';
                searchInput.focus();
            }
            resetAndRender(allDistricts);
        }

        function closePicker() {
            pickerDropdown.style.display = 'none';
            pickerTrigger.classList.remove('picker-opened');
        }

        // رویداد اسکرول نرم نامحدود (Smooth Infinite Scroll)
        listContainer.addEventListener('scroll', function() {
            const scrollPos = listContainer.scrollTop + listContainer.clientHeight;
            const scrollHeight = listContainer.scrollHeight;
            if (scrollHeight - scrollPos < 45) {
                renderNextBatch();
            }
        });

        // کلیک روی دکمه تریگر
        pickerTrigger.addEventListener('click', function(e) {
            e.stopPropagation();
            if (pickerDropdown.style.display === 'block') {
                closePicker();
            } else {
                openPicker();
            }
        });

        // جستجوی زنده (Live Instant Search)
        if (searchInput) {
            searchInput.addEventListener('input', function() {
                const q = this.value.trim().toLowerCase();
                if (!q) {
                    resetAndRender(allDistricts);
                    return;
                }
                const matches = allDistricts.filter(function(d) {
                    return d.name.toLowerCase().indexOf(q) !== -1 || (d.region && d.region.toLowerCase().indexOf(q) !== -1);
                });
                resetAndRender(matches);
            });

            searchInput.addEventListener('click', function(e) {
                e.stopPropagation();
            });
        }

        // دکمه انتخاب کل تهران
        const selectAllBtn = document.getElementById('districtPickerAllOption');
        if (selectAllBtn) {
            selectAllBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                selectDistrict('all');
            });
        }

        // دکمه حذف فیلتر محله
        if (clearBtn) {
            clearBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                selectDistrict('all');
            });
        }

        // بستن با کلیک خارج
        document.addEventListener('click', function(e) {
            if (!pickerTrigger.contains(e.target) && !pickerDropdown.contains(e.target)) {
                closePicker();
            }
        });

        // تنظیم اولیه مقدار در هنگام بارگذاری
        const initialVal = hiddenInput.value;
        if (initialVal && initialVal !== 'all') {
            selectedLabel.textContent = initialVal;
            if (clearBtn) clearBtn.style.display = 'inline-flex';
            pickerTrigger.classList.add('has-selection');
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initDistrictPicker);
    } else {
        initDistrictPicker();
    }

    window.initDistrictPicker = initDistrictPicker;
})();