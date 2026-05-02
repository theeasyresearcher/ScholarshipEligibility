/* ===================================================
   SCHOLARSHIP ELIGIBILITY CHECKER — script.js
   =================================================== */

(function () {
  "use strict";

  // ── Config ──────────────────────────────────────────
  const JSON_URL = "scholarships.json";

  // ── State ───────────────────────────────────────────
  let allScholarships = [];
  let filteredResults = [];
  let currentFilter = "all";
  let userAge = null;

  // ── DOM Refs ─────────────────────────────────────────
  const form           = document.getElementById("eligibility-form");
  const submitBtn      = document.getElementById("submit-btn");
  const resetBtn       = document.getElementById("reset-btn");
  const checkerSection = document.getElementById("checker");
  const resultsSection = document.getElementById("results-section");
  const resultsGrid    = document.getElementById("results-grid");
  const resultsTitle   = document.getElementById("results-title");
  const noResults      = document.getElementById("no-results");
  const formError      = document.getElementById("form-error");
  const statCount      = document.getElementById("stat-count");
  const filterBtns     = document.querySelectorAll(".filter-btn");

  // ── Init ─────────────────────────────────────────────
  function init() {
    // Set max DOB to today
    document.getElementById("dob").max = new Date().toISOString().split("T")[0];

    // Load scholarship data
    loadScholarships();

    // Wire events
    form.addEventListener("submit", handleSubmit);
    resetBtn.addEventListener("click", handleReset);
    filterBtns.forEach(btn => btn.addEventListener("click", handleFilter));
  }

  // ── Load Data ─────────────────────────────────────────
  async function loadScholarships() {
    try {
      const res = await fetch(JSON_URL + "?v=" + Date.now());
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      allScholarships = Array.isArray(data) ? data : (data.scholarships || []);
      statCount.textContent = allScholarships.length;
    } catch (err) {
      console.warn("Could not load scholarships.json:", err.message);
      allScholarships = getSampleData();
      statCount.textContent = allScholarships.length + "*";
    }
  }

  // ── Form Submit ───────────────────────────────────────
  function handleSubmit(e) {
    e.preventDefault();
    clearError();

    if (!validateForm()) return;

    // Collect form values
    const dob           = document.getElementById("dob").value;
    const gender        = document.getElementById("gender").value;
    const category      = document.getElementById("category").value;
    const state         = document.getElementById("state").value;
    const qualification = document.getElementById("qualification").value;
    const income        = parseInt(document.getElementById("income").value, 10);
    const marks         = parseFloat(document.getElementById("marks").value) || null;
    const disability    = document.getElementById("disability").value;

    userAge = calculateAge(dob);

    // Filter
    filteredResults = allScholarships.filter(s => matchScholarship(s, {
      age: userAge, gender, category, state, qualification, income, marks, disability
    }));

    renderResults(filteredResults);
  }

  // ── Matching Logic ────────────────────────────────────
  function matchScholarship(s, user) {
    // Age
    if (s.min_age && user.age < s.min_age) return false;
    if (s.max_age && user.age > s.max_age) return false;

    // Gender (scholarship specifies restriction)
    if (s.gender && s.gender !== "all") {
      if (s.gender.toLowerCase() !== user.gender.toLowerCase()) return false;
    }

    // Category
    if (s.categories && s.categories.length > 0) {
      const cats = s.categories.map(c => c.toLowerCase());
      if (!cats.includes("all") && !cats.includes(user.category.toLowerCase())) return false;
    }

    // State
    if (s.states && s.states.length > 0) {
      const sts = s.states.map(x => x.toLowerCase());
      if (!sts.includes("all") && !sts.includes(user.state.toLowerCase())) return false;
    }

    // Qualification
    if (s.qualifications && s.qualifications.length > 0) {
      const quals = s.qualifications.map(q => q.toLowerCase());
      if (!quals.includes("all") && !quals.includes(user.qualification.toLowerCase())) return false;
    }

    // Income
    if (s.max_income && user.income > s.max_income) return false;

    // Marks
    if (s.min_marks && user.marks !== null && user.marks < s.min_marks) return false;

    // Disability
    if (s.disability_only && user.disability !== "yes") return false;

    return true;
  }

  // ── Render Results ────────────────────────────────────
  function renderResults(data) {
    // Switch sections
    checkerSection.classList.add("hidden");
    resultsSection.classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });

    // Title
    resultsTitle.textContent =
      data.length > 0
        ? `${data.length} Eligible Scholarship${data.length > 1 ? "s" : ""} Found`
        : "No Matches Found";

    // Reset filter
    currentFilter = "all";
    filterBtns.forEach(b => b.classList.toggle("active", b.dataset.filter === "all"));

    renderCards(data);
  }

  function renderCards(data) {
    resultsGrid.innerHTML = "";
    const toShow = currentFilter === "all"
      ? data
      : data.filter(s => (s.type || "").toLowerCase() === currentFilter);

    if (toShow.length === 0) {
      noResults.classList.remove("hidden");
      return;
    }
    noResults.classList.add("hidden");

    toShow.forEach((s, i) => {
      const card = buildCard(s, i);
      resultsGrid.appendChild(card);
    });
  }

  function buildCard(s, index) {
    const card = document.createElement("article");
    card.className = "scholarship-card";
    card.style.animationDelay = (index * 0.06) + "s";

    const type = (s.type || "").toLowerCase();
    const badgeClass = type === "central" ? "badge-central"
                     : type === "state"   ? "badge-state"
                     : type === "private" ? "badge-private"
                     : "badge-default";
    const badgeLabel = type === "central" ? "Central Govt."
                     : type === "state"   ? "State Govt."
                     : type === "private" ? "Private"
                     : "Scholarship";

    const deadlineHtml = formatDeadline(s.deadline);
    const eligText     = truncate(s.eligibility || "Check official site for full eligibility criteria.", 120);
    const amount       = s.amount || "Varies";
    const categories   = (s.categories || []).filter(c => c.toLowerCase() !== "all").slice(0, 3);

    card.innerHTML = `
      <div class="card-badges">
        <span class="badge ${badgeClass}">${badgeLabel}</span>
        ${categories.map(c => `<span class="badge badge-category">${c.toUpperCase()}</span>`).join("")}
      </div>
      <h3 class="card-title">${escapeHtml(s.name || "Unnamed Scholarship")}</h3>
      <div class="card-amount">${escapeHtml(amount)}<small> per year</small></div>
      <div class="card-meta">
        <div class="card-meta-row">
          <span class="meta-icon">📋</span>
          <span><strong>Eligibility:</strong> ${escapeHtml(eligText)}</span>
        </div>
        ${s.states && !s.states.includes("All") && s.states.length < 5
          ? `<div class="card-meta-row"><span class="meta-icon">📍</span><span><strong>States:</strong> ${escapeHtml(s.states.slice(0,3).join(", "))}</span></div>`
          : ""}
        ${s.min_marks
          ? `<div class="card-meta-row"><span class="meta-icon">🎯</span><span><strong>Min Marks:</strong> ${s.min_marks}%</span></div>`
          : ""}
        ${s.max_income
          ? `<div class="card-meta-row"><span class="meta-icon">💰</span><span><strong>Income Limit:</strong> ₹${s.max_income.toLocaleString("en-IN")}</span></div>`
          : ""}
      </div>
      <div class="card-footer">
        ${deadlineHtml}
        <a href="${escapeHtml(s.link || "#")}" target="_blank" rel="noopener noreferrer" class="card-apply">
          Apply Now ↗
        </a>
      </div>
    `;
    return card;
  }

  // ── Filter Bar ────────────────────────────────────────
  function handleFilter(e) {
    currentFilter = e.target.dataset.filter;
    filterBtns.forEach(b => b.classList.toggle("active", b === e.target));
    renderCards(filteredResults);
  }

  // ── Reset ─────────────────────────────────────────────
  function handleReset() {
    resultsSection.classList.add("hidden");
    checkerSection.classList.remove("hidden");
    checkerSection.scrollIntoView({ behavior: "smooth" });
  }

  // ── Validation ────────────────────────────────────────
  function validateForm() {
    const required = ["dob", "gender", "category", "state", "qualification", "income"];
    let valid = true;

    required.forEach(id => {
      const el = document.getElementById(id);
      if (!el.value) {
        el.classList.add("invalid");
        valid = false;
      } else {
        el.classList.remove("invalid");
      }
    });

    // Remove invalid class on change
    required.forEach(id => {
      document.getElementById(id).addEventListener("change", function () {
        if (this.value) this.classList.remove("invalid");
      }, { once: true });
    });

    if (!valid) {
      showError("Please fill in all required fields (marked with *).");
    }
    return valid;
  }

  // ── Helpers ───────────────────────────────────────────
  function calculateAge(dobStr) {
    const dob  = new Date(dobStr);
    const now  = new Date();
    let age = now.getFullYear() - dob.getFullYear();
    if (now.getMonth() < dob.getMonth() ||
       (now.getMonth() === dob.getMonth() && now.getDate() < dob.getDate())) {
      age--;
    }
    return age;
  }

  function formatDeadline(deadline) {
    if (!deadline || deadline.toLowerCase() === "varies" || deadline.toLowerCase() === "n/a") {
      return `<span class="deadline-badge unknown">📅 Check Portal</span>`;
    }
    const d = new Date(deadline);
    if (isNaN(d.getTime())) {
      return `<span class="deadline-badge unknown">📅 ${deadline}</span>`;
    }
    const now = new Date();
    const diff = Math.ceil((d - now) / (1000 * 60 * 60 * 24));
    const label = d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
    if (diff < 0) return `<span class="deadline-badge">❌ Closed</span>`;
    if (diff <= 15) return `<span class="deadline-badge">⚠️ ${label}</span>`;
    return `<span class="deadline-badge ok">✅ ${label}</span>`;
  }

  function truncate(str, len) {
    return str.length > len ? str.slice(0, len) + "…" : str;
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function showError(msg) {
    formError.textContent = msg;
    formError.classList.remove("hidden");
    formError.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function clearError() {
    formError.textContent = "";
    formError.classList.add("hidden");
  }

  // ── Sample / Fallback Data ────────────────────────────
  // This is used if scholarships.json cannot be fetched locally
  function getSampleData() {
    return [
      {
        "id": "nsp-central-sector",
        "name": "Central Sector Scheme of Scholarships for College & University Students",
        "amount": "₹10,000 – ₹20,000",
        "deadline": "2025-12-31",
        "eligibility": "12th pass with min 80% marks. Annual family income below ₹4.5 lakh. Fresh and renewal students.",
        "link": "https://scholarships.gov.in",
        "type": "central",
        "categories": ["General", "OBC", "SC", "ST", "EWS"],
        "gender": "all",
        "states": ["All"],
        "qualifications": ["undergraduate"],
        "max_income": 450000,
        "min_marks": 80,
        "min_age": 17,
        "max_age": 25,
        "disability_only": false
      },
      {
        "id": "nsp-post-matric-sc",
        "name": "Post Matric Scholarship for SC Students",
        "amount": "₹1,200 – ₹7,800",
        "deadline": "2025-11-30",
        "eligibility": "SC students pursuing post-matriculation or post-secondary courses. Family income below ₹2.5 lakh.",
        "link": "https://scholarships.gov.in",
        "type": "central",
        "categories": ["SC"],
        "gender": "all",
        "states": ["All"],
        "qualifications": ["class11", "class12", "diploma", "undergraduate", "postgraduate"],
        "max_income": 250000,
        "min_marks": null,
        "min_age": null,
        "max_age": null,
        "disability_only": false
      },
      {
        "id": "nsp-minority",
        "name": "Merit cum Means Scholarship for Minority Students",
        "amount": "₹25,000",
        "deadline": "2025-10-31",
        "eligibility": "Technical/professional course students from minority communities. Family income below ₹2.5 lakh. Min 50% marks.",
        "link": "https://scholarships.gov.in",
        "type": "central",
        "categories": ["OBC"],
        "gender": "all",
        "states": ["All"],
        "qualifications": ["undergraduate", "postgraduate"],
        "max_income": 250000,
        "min_marks": 50,
        "min_age": null,
        "max_age": null,
        "disability_only": false
      },
      {
        "id": "nsp-divyangjan",
        "name": "National Fellowship and Scholarship for Higher Education of ST Students",
        "amount": "₹13,800 – ₹16,800",
        "deadline": "2025-11-15",
        "eligibility": "ST students for higher education. Annual family income up to ₹6 lakh.",
        "link": "https://scholarships.gov.in",
        "type": "central",
        "categories": ["ST"],
        "gender": "all",
        "states": ["All"],
        "qualifications": ["undergraduate", "postgraduate"],
        "max_income": 600000,
        "min_marks": 55,
        "min_age": null,
        "max_age": null,
        "disability_only": false
      },
      {
        "id": "nsp-disability",
        "name": "Scholarship for Students with Disabilities",
        "amount": "₹500 – ₹20,000",
        "deadline": "2025-12-15",
        "eligibility": "Students with benchmark disability (40%+). All categories eligible. Income limit ₹2.5 lakh.",
        "link": "https://disabilityaffairs.gov.in",
        "type": "central",
        "categories": ["General", "OBC", "SC", "ST", "EWS"],
        "gender": "all",
        "states": ["All"],
        "qualifications": ["class9", "class10", "class11", "class12", "diploma", "undergraduate", "postgraduate"],
        "max_income": 250000,
        "min_marks": null,
        "min_age": null,
        "max_age": null,
        "disability_only": true
      },
      {
        "id": "buddy4study-girls",
        "name": "Pragati Scholarship for Girls (AICTE)",
        "amount": "₹50,000",
        "deadline": "2025-12-31",
        "eligibility": "Girl students admitted to AICTE-approved institutions for technical degree/diploma courses. Family income below ₹8 lakh.",
        "link": "https://www.aicte-india.org/schemes/students-development-schemes/Pragati",
        "type": "central",
        "categories": ["General", "OBC", "SC", "ST", "EWS"],
        "gender": "female",
        "states": ["All"],
        "qualifications": ["diploma", "undergraduate"],
        "max_income": 800000,
        "min_marks": null,
        "min_age": null,
        "max_age": 30,
        "disability_only": false
      },
      {
        "id": "tm-scholarship",
        "name": "Tamil Nadu Chief Minister's Scholarship",
        "amount": "₹5,000 – ₹25,000",
        "deadline": "Varies",
        "eligibility": "Tamil Nadu domicile. SC/ST/OBC students pursuing graduation. Family income below ₹2 lakh.",
        "link": "https://adi.tn.gov.in",
        "type": "state",
        "categories": ["SC", "ST", "OBC"],
        "gender": "all",
        "states": ["Tamil Nadu"],
        "qualifications": ["undergraduate"],
        "max_income": 200000,
        "min_marks": 60,
        "min_age": null,
        "max_age": null,
        "disability_only": false
      },
      {
        "id": "mh-eklavya",
        "name": "Eklavya Scholarship (Maharashtra)",
        "amount": "₹15,000",
        "deadline": "2025-09-30",
        "eligibility": "ST students domiciled in Maharashtra pursuing higher education. Min 60% in last qualifying exam.",
        "link": "https://mahadbt.maharashtra.gov.in",
        "type": "state",
        "categories": ["ST"],
        "gender": "all",
        "states": ["Maharashtra"],
        "qualifications": ["undergraduate", "postgraduate"],
        "max_income": 250000,
        "min_marks": 60,
        "min_age": null,
        "max_age": null,
        "disability_only": false
      },
      {
        "id": "scholarise-featured-1",
        "name": "Reliance Foundation Undergraduate Scholarship",
        "amount": "₹2,00,000",
        "deadline": "2026-01-15",
        "eligibility": "First-year undergraduate students in STEM or humanities with exceptional merit. Family income below ₹6 lakh.",
        "link": "https://scholarise.in",
        "type": "private",
        "categories": ["General", "OBC", "SC", "ST", "EWS"],
        "gender": "all",
        "states": ["All"],
        "qualifications": ["undergraduate"],
        "max_income": 600000,
        "min_marks": 60,
        "min_age": 17,
        "max_age": 25,
        "disability_only": false
      },
      {
        "id": "scholarise-featured-2",
        "name": "HDFC Badhte Kadam Scholarship",
        "amount": "₹18,000 – ₹75,000",
        "deadline": "2025-10-31",
        "eligibility": "Students in class 9 to postgraduate. Annual family income below ₹1.8 lakh. Min 55% marks.",
        "link": "https://scholarise.in",
        "type": "private",
        "categories": ["General", "OBC", "SC", "ST", "EWS"],
        "gender": "all",
        "states": ["All"],
        "qualifications": ["class9", "class10", "class11", "class12", "undergraduate", "postgraduate"],
        "max_income": 180000,
        "min_marks": 55,
        "min_age": null,
        "max_age": null,
        "disability_only": false
      }
    ];
  }

  // ── Boot ──────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", init);

})();
