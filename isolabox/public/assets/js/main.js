/**
 * Isolabox - Main JS
 */

// Smooth scroll for anchor links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            e.preventDefault();
            const offset = 80;
            const y = target.getBoundingClientRect().top + window.pageYOffset - offset;
            window.scrollTo({ top: y, behavior: 'smooth' });
            document.body.classList.remove('nav-open');
        }
    });
});

// Nav background on scroll
const nav = document.querySelector('.nav');
if (nav) {
    window.addEventListener('scroll', () => {
        nav.style.borderBottomColor = window.scrollY > 50
            ? 'var(--border-light)'
            : 'var(--border)';
    }, { passive: true });
}

// Copy button feedback
document.querySelectorAll('.copy-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const original = btn.innerHTML;
        btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>';
        btn.style.color = 'var(--accent)';
        setTimeout(() => {
            btn.innerHTML = original;
            btn.style.color = '';
        }, 2000);
    });
});

// Intersection Observer for animations
const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.style.opacity = '1';
            entry.target.style.transform = 'translateY(0)';
        }
    });
}, { threshold: 0.1 });

document.querySelectorAll('.feature-card, .pricing-card, .usecase, .roadmap__phase, .problem-card').forEach(el => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(20px)';
    el.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
    observer.observe(el);
});
