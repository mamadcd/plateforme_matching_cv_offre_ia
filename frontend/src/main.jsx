import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowRight,
  Bell,
  BriefcaseBusiness,
  Check,
  ChevronRight,
  CircleUserRound,
  FileText,
  LogOut,
  Search,
  ShieldCheck,
  Sparkles,
  UsersRound,
} from "lucide-react";
import {
  BrowserRouter,
  Link,
  Navigate,
  NavLink,
  Route,
  Routes,
  useNavigate,
} from "react-router-dom";
import "./styles.css";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  let response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers,
      credentials: "include",
    });
  } catch {
    throw new Error("API indisponible. Vérifiez que le serveur backend est démarré.");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Erreur API (${response.status})`);
  }
  return response.status === 204 ? null : response.json();
}

function App() {
  const [user, setUser] = useState(null);
  const [sessionReady, setSessionReady] = useState(false);
  useEffect(() => {
    api("/auth/me")
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setSessionReady(true));
  }, []);
  async function signOut() {
    await api("/auth/logout", { method: "POST" }).catch(() => {});
    setUser(null);
  }
  if (!sessionReady) return <div className='app-loading'>matchwork</div>;
  return (
    <BrowserRouter>
      <div className='app-frame'>
        <header className='topbar'>
          <Link className='brand' to='/' aria-label='matchwork, accueil'>
            <span className='brand-mark'>
              <Activity size={18} />
            </span>
            <span>
              match<span className='brand-accent'>work</span>
            </span>
          </Link>
          <nav className='topnav' aria-label='Navigation principale'>
            <NavLink to='/'>Offres</NavLink>
            {user && <NavLink to='/espace'>Mon espace</NavLink>}
          </nav>
          <div className='account-nav'>
            {user ? (
              <>
                <span className='account-name'>
                  <CircleUserRound size={17} />
                  {user.full_name}
                </span>
                <button
                  className='icon-button'
                  onClick={signOut}
                  title='Se déconnecter'
                  aria-label='Se déconnecter'
                >
                  <LogOut size={18} />
                </button>
              </>
            ) : (
              <>
                <Link className='quiet-link' to='/connexion'>
                  Connexion
                </Link>
                <Link className='button button-small' to='/inscription'>
                  Créer un compte <ArrowRight size={15} />
                </Link>
              </>
            )}
          </div>
        </header>
        <Routes>
          <Route path='/' element={<HomePage user={user} />} />
          <Route
            path='/connexion'
            element={
              user ? <Navigate to='/espace' replace /> : <AuthPage mode='login' onAuth={setUser} />
            }
          />
          <Route
            path='/inscription'
            element={
              user ? (
                <Navigate to='/espace' replace />
              ) : (
                <AuthPage mode='register' onAuth={setUser} />
              )
            }
          />
          <Route
            path='/espace'
            element={user ? <Dashboard user={user} /> : <Navigate to='/connexion' replace />}
          />
          <Route path='*' element={<Navigate to='/' replace />} />
        </Routes>
        <footer className='site-footer'>
          <span>matchwork</span>
          <span>Matching assisté, décisions humaines.</span>
        </footer>
      </div>
    </BrowserRouter>
  );
}

function HomePage({ user }) {
  const [jobs, setJobs] = useState([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    api("/jobs")
      .then(setJobs)
      .catch((requestError) => setError(requestError.message));
  }, []);
  const visibleJobs = jobs.filter((job) =>
    `${job.title} ${job.company} ${job.location} ${job.required_skills.join(" ")}`
      .toLocaleLowerCase("fr")
      .includes(query.toLocaleLowerCase("fr")),
  );
  return (
    <main className='page-content'>
      <section className='intro-band'>
        <div>
          <span className='eyebrow'>Opportunités ouvertes</span>
          <h1>Trouvez votre prochain rôle.</h1>
          <p>Explorez les offres et comparez les compétences qui comptent pour chaque poste.</p>
        </div>
        <div className='intro-count'>
          <strong>{jobs.length.toString().padStart(2, "0")}</strong>
          <span>offres visibles</span>
        </div>
      </section>
      <section className='public-layout'>
        <div className='job-browser'>
          <div className='section-head'>
            <div>
              <span className='eyebrow'>Catalogue</span>
              <h2>Offres récentes</h2>
            </div>
            <label className='search-box'>
              <Search size={17} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder='Intitulé, lieu, compétence'
              />
            </label>
          </div>
          {error && <Notice tone='error'>{error}</Notice>}
          {!error && visibleJobs.length === 0 && (
            <p className='empty-state'>Aucune offre ne correspond à cette recherche.</p>
          )}
          <div className='job-list'>
            {visibleJobs.map((job, index) => (
              <article className='job-card' key={job.id}>
                <div className='job-index'>{String(index + 1).padStart(2, "0")}</div>
                <div className='job-info'>
                  <span className='eyebrow'>
                    {job.company} <span className='dot-separator'>·</span>{" "}
                    {job.location || "Lieu à préciser"}
                  </span>
                  <h3>{job.title}</h3>
                  <p>{job.description}</p>
                  <div className='tag-row'>
                    {job.required_skills.slice(0, 5).map((skill) => (
                      <span className='skill-tag' key={skill}>
                        {skill}
                      </span>
                    ))}
                  </div>
                </div>
                <Link
                  className='arrow-link'
                  to={user ? "/espace" : "/inscription"}
                  title='Créer un compte pour postuler'
                  aria-label={`Postuler à ${job.title}`}
                >
                  <ChevronRight size={20} />
                </Link>
              </article>
            ))}
          </div>
        </div>
        <aside className='visitor-panel'>
          <div className='visitor-heading'>
            <div className='panel-symbol'>
              <Sparkles size={19} />
            </div>
            <span className='eyebrow'>Sans compte</span>
          </div>
          <h2>Un premier regard sur votre match.</h2>
          <p>
            Importez un CV pour le comparer aux offres publiques. Trois analyses par jour, sans
            conservation de profil.
          </p>
          <FileMatcher role='visitor' />
          <div className='privacy-note'>
            <ShieldCheck size={16} />
            <span>Votre CV n’est pas enregistré dans votre espace.</span>
          </div>
        </aside>
      </section>
    </main>
  );
}

function AuthPage({ mode, onAuth }) {
  const navigate = useNavigate();
  const registering = mode === "register";
  const [form, setForm] = useState({ email: "", full_name: "", password: "", role: "candidate" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const currentUser = await api(registering ? "/auth/register" : "/auth/login", {
        method: "POST",
        body: JSON.stringify(registering ? form : { email: form.email, password: form.password }),
      });
      onAuth(currentUser);
      navigate("/espace");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className='auth-page'>
      <div className='auth-aside'>
        <span className='eyebrow'>matchwork / accès sécurisé</span>
        <h1>{registering ? "Votre prochain chapitre commence ici." : "Retrouvez votre espace."}</h1>
        <p>Un espace dédié à chaque étape du recrutement, avec des accès adaptés à votre rôle.</p>
        <div className='role-lines'>
          <span>
            <FileText size={17} /> Candidat
          </span>
          <span>
            <BriefcaseBusiness size={17} /> Recruteur
          </span>
          <span>
            <ShieldCheck size={17} /> Administration
          </span>
        </div>
      </div>
      <form className='auth-form' onSubmit={submit}>
        <span className='eyebrow'>{registering ? "Créer un compte" : "Connexion"}</span>
        <h2>{registering ? "Rejoindre matchwork" : "Bon retour"}</h2>
        {registering && (
          <>
            <label>
              Nom complet
              <input
                required
                minLength={2}
                maxLength={160}
                value={form.full_name}
                onChange={(event) => setForm({ ...form, full_name: event.target.value })}
                autoComplete='name'
              />
            </label>
            <label>
              Votre profil
              <select
                value={form.role}
                onChange={(event) => setForm({ ...form, role: event.target.value })}
              >
                <option value='candidate'>Chercheur·euse d’emploi</option>
                <option value='recruiter'>Recruteur·euse</option>
              </select>
            </label>
          </>
        )}
        <label>
          Adresse e-mail
          <input
            required
            type='email'
            value={form.email}
            onChange={(event) => setForm({ ...form, email: event.target.value })}
            autoComplete='email'
          />
        </label>
        <label>
          Mot de passe
          <input
            required
            minLength={registering ? 12 : 1}
            type='password'
            value={form.password}
            onChange={(event) => setForm({ ...form, password: event.target.value })}
            autoComplete={registering ? "new-password" : "current-password"}
          />
          {registering && <small>12 caractères minimum</small>}
        </label>
        {error && <Notice tone='error'>{error}</Notice>}
        <button className='button button-full' disabled={busy}>
          {busy ? "Patientez…" : registering ? "Créer mon compte" : "Se connecter"}
          <ArrowRight size={16} />
        </button>
        <p className='switch-auth'>
          {registering ? "Déjà inscrit·e ?" : "Pas encore de compte ?"}{" "}
          <Link to={registering ? "/connexion" : "/inscription"}>
            {registering ? "Connexion" : "Inscription"}
          </Link>
        </p>
      </form>
    </main>
  );
}

function Dashboard({ user }) {
  return (
    <main className='page-content dashboard-page'>
      <div className='dashboard-title'>
        <div>
          <span className='eyebrow'>Espace {roleLabel(user.role)}</span>
          <h1>Bonjour, {user.full_name.split(" ")[0]}.</h1>
          <p>Votre activité, au même endroit.</p>
        </div>
        <span className='role-pill'>
          <ShieldCheck size={15} />
          {roleLabel(user.role)}
        </span>
      </div>
      {user.role === "candidate" && <CandidateDashboard />}
      {user.role === "recruiter" && <RecruiterDashboard />}
      {user.role === "admin" && <AdminDashboard />}
    </main>
  );
}

function CandidateDashboard() {
  const [profile, setProfile] = useState(null);
  const [applications, setApplications] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [error, setError] = useState("");
  async function refresh() {
    const values = await Promise.all([
      api("/candidate/profile").catch(() => null),
      api("/candidate/applications").catch(() => []),
      api("/candidate/notifications").catch(() => []),
    ]);
    setProfile(values[0]);
    setApplications(values[1]);
    setNotifications(values[2]);
  }
  useEffect(() => {
    refresh().catch((requestError) => setError(requestError.message));
  }, []);
  async function apply(jobId) {
    try {
      await api("/candidate/applications", {
        method: "POST",
        body: JSON.stringify({ job_id: jobId }),
      });
      await refresh();
    } catch (requestError) {
      setError(requestError.message);
    }
  }
  return (
    <>
      {error && <Notice tone='error'>{error}</Notice>}
      <div className='dashboard-grid candidate-grid'>
        <section className='workspace-section'>
          <SectionHeading
            icon={<FileText size={18} />}
            eyebrow='Mon profil'
            title={profile ? "Mettre à jour mon CV" : "Ajouter mon CV"}
          />
          {profile && (
            <div className='saved-profile'>
              <Check size={16} />
              <span>{profile.full_name}</span>
              <small>{profile.skills.length} compétences extraites</small>
            </div>
          )}
          <FileMatcher role='candidate' onSaved={refresh} onApply={apply} />
          <p className='field-note'>
            Le partage du CV avec les recruteurs est désactivé par défaut. Vous pouvez l’activer
            avant l’enregistrement.
          </p>
        </section>
        <section className='workspace-section'>
          <SectionHeading
            icon={<BriefcaseBusiness size={18} />}
            eyebrow='Suivi'
            title='Mes candidatures'
            count={applications.length}
          />
          {applications.length === 0 ? (
            <p className='empty-state'>Aucune candidature pour le moment.</p>
          ) : (
            <div className='compact-list'>
              {applications.map((item) => (
                <div className='compact-row' key={item.id}>
                  <div>
                    <strong>{item.job_title}</strong>
                    <small>{new Date(item.created_at).toLocaleDateString("fr-FR")}</small>
                  </div>
                  <StatusTag status={item.status} />
                </div>
              ))}
            </div>
          )}
        </section>
        <section className='workspace-section notification-section'>
          <SectionHeading
            icon={<Bell size={18} />}
            eyebrow='À suivre'
            title='Notifications'
            count={notifications.filter((item) => !item.is_read).length}
          />
          {notifications.length === 0 ? (
            <p className='empty-state'>Vous êtes à jour.</p>
          ) : (
            <div className='compact-list'>
              {notifications.map((item) => (
                <div className={`notification-row ${item.is_read ? "read" : ""}`} key={item.id}>
                  <span className='notification-dot' />
                  <p>{item.message}</p>
                  <button
                    className='text-button'
                    onClick={() =>
                      api(`/candidate/notifications/${item.id}`, { method: "PATCH" }).then(refresh)
                    }
                  >
                    Marquer lu
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </>
  );
}

function RecruiterDashboard() {
  const [jobs, setJobs] = useState([]);
  const [selectedJob, setSelectedJob] = useState(null);
  const [candidates, setCandidates] = useState([]);
  const [shortlist, setShortlist] = useState([]);
  const [applications, setApplications] = useState([]);
  const [error, setError] = useState("");
  async function refresh() {
    setJobs(await api("/recruiter/jobs"));
  }
  useEffect(() => {
    refresh().catch((requestError) => setError(requestError.message));
  }, []);
  async function publish(job, isPublished) {
    try {
      await api(`/recruiter/jobs/${job.id}/publication`, {
        method: "PATCH",
        body: JSON.stringify({ is_published: isPublished }),
      });
      await refresh();
    } catch (requestError) {
      setError(requestError.message);
    }
  }
  async function showCandidates(job) {
    setSelectedJob(job);
    setError("");
    try {
      const values = await Promise.all([
        api(`/recruiter/jobs/${job.id}/candidates`),
        api(`/recruiter/jobs/${job.id}/shortlist`),
        api(`/recruiter/jobs/${job.id}/applications`),
      ]);
      setCandidates(values[0]);
      setShortlist(values[1]);
      setApplications(values[2]);
    } catch (requestError) {
      setError(requestError.message);
    }
  }
  async function addShortlist(candidateId) {
    if (!selectedJob) return;
    try {
      await api(`/recruiter/jobs/${selectedJob.id}/shortlist/${candidateId}`, { method: "POST" });
      await showCandidates(selectedJob);
    } catch (requestError) {
      setError(requestError.message);
    }
  }
  async function updateApplication(applicationId, nextStatus) {
    try {
      await api(`/recruiter/applications/${applicationId}`, {
        method: "PATCH",
        body: JSON.stringify({ status: nextStatus }),
      });
      await showCandidates(selectedJob);
    } catch (requestError) {
      setError(requestError.message);
    }
  }
  return (
    <>
      {error && <Notice tone='error'>{error}</Notice>}
      <div className='dashboard-grid recruiter-grid'>
        <section className='workspace-section'>
          <SectionHeading
            icon={<BriefcaseBusiness size={18} />}
            eyebrow='Publication'
            title='Créer une offre'
          />
          <NewJobForm onCreated={refresh} />
        </section>
        <section className='workspace-section recruiter-jobs'>
          <SectionHeading
            icon={<FileText size={18} />}
            eyebrow='Votre organisation'
            title='Mes offres'
            count={jobs.length}
          />
          {jobs.length === 0 ? (
            <p className='empty-state'>Aucune offre créée.</p>
          ) : (
            jobs.map((job) => (
              <article className='recruiter-job-row' key={job.id}>
                <div>
                  <span className={`publication-state ${job.is_published ? "published" : "draft"}`}>
                    {job.is_published ? "Publiée" : "Brouillon"}
                  </span>
                  <h3>{job.title}</h3>
                  <p>
                    {job.company} · {job.location || "Lieu à préciser"}
                  </p>
                </div>
                <div className='job-actions'>
                  <button className='text-button' onClick={() => showCandidates(job)}>
                    Candidats
                  </button>
                  <button
                    className='button button-small'
                    onClick={() => publish(job, !job.is_published)}
                  >
                    {job.is_published ? "Dépublier" : "Publier"}
                  </button>
                </div>
              </article>
            ))
          )}
        </section>
        {selectedJob && (
          <>
            <section className='workspace-section application-pipeline'>
              <SectionHeading
                icon={<BriefcaseBusiness size={18} />}
                eyebrow={selectedJob.title}
                title='Candidatures reçues'
                count={applications.length}
              />
              {applications.length === 0 ? (
                <p className='empty-state'>Aucune candidature reçue pour cette offre.</p>
              ) : (
                applications.map((application) => (
                  <article className='application-row' key={application.id}>
                    <div className='application-person'>
                      <strong>{application.candidate_name}</strong>
                      <a href={`mailto:${application.candidate_email}`}>
                        {application.candidate_email}
                      </a>
                    </div>
                    <time>{new Date(application.created_at).toLocaleDateString("fr-FR")}</time>
                    <label className='status-control'>
                      <span className='sr-only'>
                        Statut de la candidature de {application.candidate_name}
                      </span>
                      <select
                        value={application.status}
                        onChange={(event) => updateApplication(application.id, event.target.value)}
                      >
                        <option value='applied' disabled>
                          Reçue
                        </option>
                        <option value='review'>En examen</option>
                        <option value='interview'>Entretien</option>
                        <option value='rejected'>Clôturée</option>
                        <option value='accepted'>Retenue</option>
                      </select>
                    </label>
                  </article>
                ))
              )}
            </section>
            <section className='workspace-section candidate-matches'>
              <SectionHeading
                icon={<UsersRound size={18} />}
                eyebrow={selectedJob.title}
                title='Profils consentants recommandés'
                count={candidates.length}
              />
              {candidates.length === 0 ? (
                <p className='empty-state'>
                  Aucun profil visible ne correspond encore. Les candidats doivent avoir enregistré
                  leur CV et activé sa visibilité.
                </p>
              ) : (
                candidates.map((candidate) => (
                  <article className='candidate-row' key={candidate.cv_id}>
                    <div>
                      <strong>{candidate.cv_name}</strong>
                      <p>{candidate.explanation}</p>
                      <div className='tag-row'>
                        {candidate.matched_skills.slice(0, 4).map((skill) => (
                          <span className='skill-tag' key={skill}>
                            {skill}
                          </span>
                        ))}
                      </div>
                    </div>
                    <div className='candidate-actions'>
                      <strong className='match-score'>
                        {Math.round(candidate.score)}
                        <small>/100</small>
                      </strong>
                      <button
                        className='text-button'
                        disabled={shortlist.some((item) => item.candidate_id === candidate.cv_id)}
                        onClick={() => addShortlist(candidate.cv_id)}
                      >
                        {shortlist.some((item) => item.candidate_id === candidate.cv_id)
                          ? "Dans la shortlist"
                          : "Ajouter"}
                      </button>
                    </div>
                  </article>
                ))
              )}
            </section>
          </>
        )}
      </div>
    </>
  );
}

function NewJobForm({ onCreated }) {
  const [form, setForm] = useState({
    title: "",
    company: "",
    location: "",
    description: "",
    skills: "",
  });
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      await api("/recruiter/jobs", {
        method: "POST",
        body: JSON.stringify({
          title: form.title,
          company: form.company,
          location: form.location,
          description: form.description,
          required_skills: form.skills
            .split(",")
            .map((skill) => skill.trim())
            .filter(Boolean),
        }),
      });
      setForm({ title: "", company: "", location: "", description: "", skills: "" });
      setSaved(true);
      onCreated();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className='stack-form' onSubmit={submit}>
      <label>
        Intitulé
        <input
          required
          minLength={2}
          value={form.title}
          onChange={(event) => setForm({ ...form, title: event.target.value })}
        />
      </label>
      <div className='form-two'>
        <label>
          Entreprise
          <input
            required
            minLength={2}
            value={form.company}
            onChange={(event) => setForm({ ...form, company: event.target.value })}
          />
        </label>
        <label>
          Lieu
          <input
            value={form.location}
            onChange={(event) => setForm({ ...form, location: event.target.value })}
          />
        </label>
      </div>
      <label>
        Description
        <textarea
          required
          minLength={20}
          rows={5}
          value={form.description}
          onChange={(event) => setForm({ ...form, description: event.target.value })}
        />
      </label>
      <label>
        Compétences requises <small>Séparées par des virgules</small>
        <input
          value={form.skills}
          onChange={(event) => setForm({ ...form, skills: event.target.value })}
          placeholder='Python, SQL, Docker'
        />
      </label>
      {error && <Notice tone='error'>{error}</Notice>}
      {saved && <Notice tone='success'>Offre enregistrée en brouillon.</Notice>}
      <button className='button' disabled={busy}>
        {busy ? "Enregistrement…" : "Enregistrer le brouillon"}
        <ArrowRight size={16} />
      </button>
    </form>
  );
}

function AdminDashboard() {
  const [overview, setOverview] = useState(null);
  const [users, setUsers] = useState([]);
  const [error, setError] = useState("");
  async function refresh() {
    const values = await Promise.all([api("/admin/overview"), api("/admin/users")]);
    setOverview(values[0]);
    setUsers(values[1]);
  }
  useEffect(() => {
    refresh().catch((requestError) => setError(requestError.message));
  }, []);
  async function updateUser(user, patch) {
    try {
      await api(`/admin/users/${user.id}`, { method: "PATCH", body: JSON.stringify(patch) });
      await refresh();
    } catch (requestError) {
      setError(requestError.message);
    }
  }
  return (
    <div className='admin-layout'>
      {error && <Notice tone='error'>{error}</Notice>}
      <section className='workspace-section admin-overview'>
        <SectionHeading
          icon={<Activity size={18} />}
          eyebrow='État de la plateforme'
          title='Vue d’ensemble'
        />
        <div className='metric-row'>
          <Metric label='Comptes' value={overview?.users_total} />
          <Metric label='Offres publiées' value={overview?.published_jobs} />
          <Metric label='Candidatures' value={overview?.applications_total} />
          <Metric
            label='Matchings visiteurs aujourd’hui'
            value={overview?.anonymous_matches_today}
          />
        </div>
      </section>
      <section className='workspace-section user-management'>
        <SectionHeading
          icon={<UsersRound size={18} />}
          eyebrow='Accès & comptes'
          title='Utilisateurs'
          count={users.length}
        />
        <div className='user-table-wrap'>
          <table className='user-table'>
            <thead>
              <tr>
                <th>Utilisateur</th>
                <th>Rôle</th>
                <th>État</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((item) => (
                <tr key={item.id}>
                  <td>
                    <strong>{item.full_name}</strong>
                    <small>{item.email}</small>
                  </td>
                  <td>
                    <select
                      value={item.role}
                      onChange={(event) => updateUser(item, { role: event.target.value })}
                    >
                      <option value='candidate'>Candidat</option>
                      <option value='recruiter'>Recruteur</option>
                      <option value='admin'>Administrateur</option>
                    </select>
                  </td>
                  <td>
                    <span className={`user-state ${item.is_active ? "active" : "inactive"}`}>
                      {item.is_active ? "Actif" : "Désactivé"}
                    </span>
                  </td>
                  <td>
                    <button
                      className='text-button'
                      onClick={() => updateUser(item, { is_active: !item.is_active })}
                    >
                      {item.is_active ? "Désactiver" : "Réactiver"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className='workspace-section admin-capabilities'>
        <SectionHeading
          icon={<ShieldCheck size={18} />}
          eyebrow='Gouvernance IA'
          title='Contrôles système'
        />
        <div className='capability-row'>
          <div>
            <strong>Fournisseur IA</strong>
            <small>
              {overview?.ai_provider || "Chargement…"} · configuration au niveau serveur
            </small>
          </div>
          <span className='state-label'>Lecture seule</span>
        </div>
        <div className='capability-row'>
          <div>
            <strong>Suivi des biais</strong>
            <small>Aucun historique de décisions ni jeu d’évaluation configuré.</small>
          </div>
          <span className='state-label unavailable'>Non disponible</span>
        </div>
        <div className='capability-row'>
          <div>
            <strong>Réentraînement</strong>
            <small>Aucun pipeline ou modèle entraînable n’est connecté à l’application.</small>
          </div>
          <span className='state-label unavailable'>Non disponible</span>
        </div>
      </section>
    </div>
  );
}

function FileMatcher({ role, onSaved, onApply }) {
  const [file, setFile] = useState(null);
  const [searchable, setSearchable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  async function analyze(event) {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const body = new FormData();
      body.append("file", file);
      const parsed = await api(`/ingest/${role === "recruiter" ? "job" : "cv"}`, {
        method: "POST",
        body,
      });
      if (role === "candidate") {
        await api("/candidate/profile", {
          method: "PUT",
          body: JSON.stringify({ ...parsed, searchable }),
        });
        setResult(await api("/candidate/recommendations", { method: "POST" }));
        onSaved?.();
      } else
        setResult(await api("/match/anonymous", { method: "POST", body: JSON.stringify(parsed) }));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <form className='file-form' onSubmit={analyze}>
        <label className='file-picker'>
          <FileText size={19} />
          <span>{file ? file.name : "Choisir un CV (PDF, DOCX, TXT…)"}</span>
          <input
            type='file'
            accept='.pdf,.docx,.png,.jpg,.jpeg,.webp,.tiff,.tif,.bmp,.txt,.md,.csv'
            onChange={(event) => setFile(event.target.files?.[0] || null)}
          />
        </label>
        {role === "candidate" && (
          <label className='consent-option'>
            <input
              type='checkbox'
              checked={searchable}
              onChange={(event) => setSearchable(event.target.checked)}
            />
            <span>
              J’accepte que mon profil soit visible par les recruteurs pour leurs offres publiées.
            </span>
          </label>
        )}
        <button className='button' disabled={!file || busy}>
          {busy
            ? "Analyse en cours…"
            : role === "candidate"
              ? "Enregistrer et voir les recommandations"
              : "Analyser les offres publiques"}
          <Sparkles size={16} />
        </button>
      </form>
      {error && <Notice tone='error'>{error}</Notice>}
      {result && <ResultList result={result} candidate={role === "candidate"} onApply={onApply} />}
    </>
  );
}

function ResultList({ result, candidate, onApply }) {
  return (
    <div className='match-list'>
      <div className='match-list-heading'>
        <span className='eyebrow'>Recommandations</span>
        <strong>{result.matches?.length || 0} résultats</strong>
      </div>
      {(result.matches || []).map((match) => (
        <article className='match-result' key={match.job_id || match.cv_id}>
          <div className='match-result-main'>
            <h3>{match.job_title || match.cv_name}</h3>
            <p>{match.explanation}</p>
            <div className='tag-row'>
              {(match.matched_skills || match.strengths || []).slice(0, 5).map((skill) => (
                <span className='skill-tag' key={skill}>
                  {skill}
                </span>
              ))}
            </div>
            {match.gaps?.length > 0 && (
              <p className='gap-line'>
                <span>À renforcer</span> {match.gaps.slice(0, 2).join(" · ")}
              </p>
            )}
          </div>
          <div className='match-result-side'>
            <strong className='match-score'>
              {Math.round(match.score)}
              <small>/100</small>
            </strong>
            {candidate && (
              <button className='text-button' onClick={() => onApply?.(match.job_id)}>
                Postuler <ArrowRight size={14} />
              </button>
            )}
          </div>
        </article>
      ))}
    </div>
  );
}

function SectionHeading({ icon, eyebrow, title, count }) {
  return (
    <div className='section-heading'>
      <div className='section-icon'>{icon}</div>
      <div>
        <span className='eyebrow'>{eyebrow}</span>
        <h2>{title}</h2>
      </div>
      {count !== undefined && <span className='section-count'>{count}</span>}
    </div>
  );
}
function Metric({ label, value }) {
  return (
    <div className='metric'>
      <strong>{value ?? "—"}</strong>
      <span>{label}</span>
    </div>
  );
}
function Notice({ tone = "info", children }) {
  return (
    <div className={`notice ${tone}`} role={tone === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}
function StatusTag({ status }) {
  const labels = {
    applied: "Envoyée",
    review: "En examen",
    interview: "Entretien",
    rejected: "Clôturée",
    accepted: "Retenue",
  };
  return <span className={`status-tag ${status}`}>{labels[status] || status}</span>;
}
function roleLabel(role) {
  return { candidate: "candidat", recruiter: "recruteur", admin: "administrateur" }[role] || role;
}

function Root() {
  return <App />;
}

createRoot(document.getElementById("root")).render(<Root />);
