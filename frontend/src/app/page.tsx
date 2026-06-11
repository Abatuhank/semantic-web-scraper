"use client";

import { useState, useEffect, FormEvent } from 'react';
import ReactMarkdown from 'react-markdown';
import { Search, Loader2, Link as LinkIcon, Sparkles, CheckCircle2, AlertCircle, FileText } from 'lucide-react';
import styles from './page.module.css';

interface ScrapeResult {
  url: string;
  query: string;
  raw_text_length?: number;
  combined_text_length?: number;
  total_pages_visited?: number;
  llm_answer: string;
}

export default function Home() {
  const [url, setUrl] = useState('');
  const [query, setQuery] = useState('');
  const [isDeepScrape, setIsDeepScrape] = useState(false);
  const [maxPages, setMaxPages] = useState('10');
  const [linkPattern, setLinkPattern] = useState('');
  
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<'idle' | 'polling' | 'done' | 'error'>('idle');
  const [result, setResult] = useState<ScrapeResult | null>(null);
  const [errorMsg, setErrorMsg] = useState('');
  const [elapsedTime, setElapsedTime] = useState(0);

  // Timer for UX
  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (status === 'polling') {
      interval = setInterval(() => setElapsedTime(prev => prev + 1), 1000);
    } else {
      setElapsedTime(0);
    }
    return () => clearInterval(interval);
  }, [status]);

  // Polling mechanism
  useEffect(() => {
    if (status !== 'polling' || !jobId) return;

    const poll = async () => {
      try {
        const res = await fetch(`http://localhost:8000/api/scrape/status/${jobId}`);
        if (!res.ok) throw new Error('API yanıt vermedi');
        
        const data = await res.json();
        
        if (data.status === 'done') {
          setStatus('done');
          setResult(data.result);
        } else if (data.status === 'failed') {
          setStatus('error');
          setErrorMsg(data.error || 'İşlem başarısız oldu.');
        }
      } catch (err: any) {
        setStatus('error');
        setErrorMsg(err.message || 'Bağlantı hatası.');
      }
    };

    const intervalId = setInterval(poll, 3000); // Her 3 saniyede bir kontrol et
    return () => clearInterval(intervalId);
  }, [jobId, status]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!url || !query) return;

    setStatus('polling');
    setResult(null);
    setErrorMsg('');
    setJobId(null);

    const endpoint = isDeepScrape ? '/api/scrape/deep' : '/api/scrape/analyze';
    const body: any = { url, query, timeout_ms: 60000 };
    
    if (isDeepScrape) {
      body.max_pages = parseInt(maxPages) || 10;
      if (linkPattern) body.link_pattern = linkPattern;
    }

    try {
      const res = await fetch(`http://localhost:8000${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });

      if (!res.ok) throw new Error('İstek gönderilemedi');
      
      const data = await res.json();
      setJobId(data.job_id);
    } catch (err: any) {
      setStatus('error');
      setErrorMsg(err.message || 'Bir hata oluştu.');
    }
  };

  return (
    <main className={styles.container}>
      <header className={`${styles.header} animate-fade-in`}>
        <h1 className={styles.title}>
          <Sparkles className="inline-block mr-3 mb-2 text-indigo-400" size={36} />
          Semantic Scraper
        </h1>
        <p className={styles.subtitle}>İstediğiniz siteyi verin, sorunuzu sorun. Yapay zeka gerisini halletsin.</p>
      </header>

      <form onSubmit={handleSubmit} className="glass-panel animate-fade-in" style={{ animationDelay: '0.1s' }}>
        <div className={styles.formGroup}>
          <label>Hedef URL</label>
          <div style={{ position: 'relative' }}>
            <LinkIcon size={18} color="var(--muted)" style={{ position: 'absolute', left: '16px', top: '14px' }} />
            <input 
              type="url" 
              placeholder="https://amazon.com.tr/..." 
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              required
              style={{ paddingLeft: '44px' }}
            />
          </div>
        </div>

        <div className={styles.formGroup}>
          <label>Ne öğrenmek istiyorsunuz?</label>
          <div style={{ position: 'relative' }}>
            <Search size={18} color="var(--muted)" style={{ position: 'absolute', left: '16px', top: '14px' }} />
            <textarea 
              placeholder="Örn: Sayfadaki en ucuz laptop hangisi ve fiyatı nedir?" 
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              required
              style={{ paddingLeft: '44px', minHeight: '80px' }}
            />
          </div>
        </div>

        <div className={styles.formGroup} style={{ marginTop: '24px' }}>
          <label className={styles.checkboxLabel}>
            <input 
              type="checkbox" 
              checked={isDeepScrape} 
              onChange={(e) => setIsDeepScrape(e.target.checked)} 
            />
            Gelişmiş Tarama (Çoklu Sayfa / Alt Linkleri Gez)
          </label>
        </div>

        {isDeepScrape && (
          <div className={`${styles.formRow} animate-fade-in`}>
            <div>
              <label>Maksimum Alt Sayfa</label>
              <input 
                type="number" 
                min="1" 
                max="50" 
                value={maxPages}
                onChange={(e) => setMaxPages(e.target.value)}
              />
            </div>
            <div>
              <label>Link Filtresi (Opsiyonel Regex)</label>
              <input 
                type="text" 
                placeholder="Örn: /product/.*" 
                value={linkPattern}
                onChange={(e) => setLinkPattern(e.target.value)}
              />
            </div>
          </div>
        )}

        <button type="submit" className={styles.submitBtn} disabled={status === 'polling'}>
          {status === 'polling' ? (
            <><Loader2 className="animate-spin" size={20} /> Analiz Ediliyor...</>
          ) : (
            <><Sparkles size={20} /> Veriyi Çıkar</>
          )}
        </button>
      </form>

      {status === 'polling' && (
        <div className={`${styles.statusContainer} animate-fade-in`}>
          <Loader2 className="animate-spin" size={24} />
          <div>
            <div>Sayfa taranıyor ve yapay zeka tarafından inceleniyor...</div>
            <div style={{ fontSize: '0.85rem', opacity: 0.8, marginTop: '4px' }}>Geçen süre: {elapsedTime}s</div>
          </div>
        </div>
      )}

      {status === 'error' && (
        <div className={`${styles.errorBox} animate-fade-in`}>
          <AlertCircle size={24} />
          <div>
            <strong>Hata Oluştu</strong>
            <p style={{ margin: '4px 0 0 0', fontSize: '0.9rem' }}>{errorMsg}</p>
          </div>
        </div>
      )}

      {status === 'done' && result && (
        <div className="glass-panel animate-fade-in">
          <div className={styles.resultHeader}>
            <h2 className={styles.resultTitle}>
              <CheckCircle2 color="var(--success)" size={28} />
              Analiz Sonucu
            </h2>
            <div style={{ display: 'flex', gap: '8px' }}>
              {(result.raw_text_length || result.combined_text_length) && (
                <span className={styles.badge}>
                  <FileText size={12} style={{ display: 'inline', marginRight: '4px', marginBottom: '-2px' }} />
                  {(result.raw_text_length || result.combined_text_length)?.toLocaleString('tr-TR')} karakter okundu
                </span>
              )}
              {result.total_pages_visited && (
                <span className={styles.badge}>{result.total_pages_visited} sayfa gezildi</span>
              )}
            </div>
          </div>
          
          <div className="prose">
            <ReactMarkdown>{result.llm_answer}</ReactMarkdown>
          </div>
        </div>
      )}
    </main>
  );
}
