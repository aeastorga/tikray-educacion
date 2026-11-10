// Menú lateral del panel del colegio. Solo muestra los módulos que el rol permite.
import {
  BookUser, CalendarCheck, CalendarDays, CircleDollarSign, History, IdCard, KeyRound, LayoutDashboard, LogOut, Menu as IconoMenu, NotebookPen, Presentation,
  ScanLine, Settings, ShieldCheck, UsersRound, Wallet, X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { api } from '../api.js'
import { iniciales } from '../tema.js'
import { Apariencia } from '../Apariencia.jsx'
import { Logo } from './Acceso.jsx'
import './menu.css'

export default function Menu({ colegio, yo, puede, salir }) {
  const { pathname } = useLocation()
  const [abierto, setAbierto] = useState(false)
  const [datos, setDatos] = useState({})

  // Año escolar y contadores: al entrar, al cambiar de pantalla y cada minuto.
  useEffect(() => {
    let vivo = true
    const cargar = () => api('/api/panel/menu', { sinSalir: true }).then((d) => vivo && setDatos(d)).catch(() => {})
    cargar()
    const t = setInterval(cargar, 60000)
    return () => { vivo = false; clearInterval(t) }
  }, [pathname])
  useEffect(() => { setAbierto(false) }, [pathname])
  useEffect(() => {
    if (!abierto) return undefined
    const cerrar = (e) => { if (e.key === 'Escape') setAbierto(false) }
    window.addEventListener('keydown', cerrar)
    return () => window.removeEventListener('keydown', cerrar)
  }, [abierto])

  const enAsistencia = pathname.startsWith('/panel/asistencia') && !pathname.startsWith('/panel/asistencia/porteria')
  const grupos = [
    ['Día a día', [
      { a: '/panel', texto: 'Inicio', icono: LayoutDashboard, fin: true },
      puede('asistencia') && { a: '/panel/asistencia', texto: 'Asistencia', icono: CalendarCheck, activo: enAsistencia },
      puede('asistencia', 'editar') && { a: '/panel/asistencia/porteria', texto: 'Portería', icono: ScanLine, vivo: true },
      puede('cuaderno') && { a: '/panel/cuaderno', texto: 'Cuaderno de control', icono: NotebookPen,
        contador: datos.cuaderno_pendientes, titulo: 'pendientes de aprobar' },
      puede('calendario') && { a: '/panel/calendario', texto: 'Calendario', icono: CalendarDays },
      puede('caja') && { a: '/panel/caja', texto: 'Caja', icono: Wallet },
    ]],
    ['Familias', [
      puede('familias') && { a: '/panel/familias', texto: 'Cuentas de padres', icono: UsersRound,
        contador: datos.padres_por_aprobar, titulo: 'esperan aprobación' },
      puede('reuniones') && { a: '/panel/reunion', texto: 'Reunión de padres', icono: Presentation },
    ]],
    ['Colegio', [
      puede('padron') && { a: '/panel/padron', texto: 'Padrón', icono: BookUser },
      puede('pensiones') && { a: '/panel/pensiones', texto: 'Pensiones', icono: CircleDollarSign },
      puede('personal') && { a: '/panel/personal', texto: 'Personal', icono: IdCard },
      puede('roles') && { a: '/panel/roles', texto: 'Roles y permisos', icono: ShieldCheck },
      puede('configuracion') && { a: '/panel/configuracion', texto: 'Configuración', icono: Settings },
      yo.es_administrador && { a: '/panel/historial', texto: 'Historial', icono: History },
    ]],
  ].map(([titulo, items]) => [titulo, items.filter(Boolean)]).filter(([, items]) => items.length)

  return (
    <>
      <header className="barra-movil">
        <button type="button" className="boton-icono" aria-label="Abrir menú" aria-expanded={abierto}
                aria-controls="menu-lateral" onClick={() => setAbierto(true)}>
          <IconoMenu aria-hidden="true" />
        </button>
        <Logo colegio={colegio} className="barra-movil-logo" />
        <span className="barra-movil-nombre">{colegio.nombre}</span>
      </header>
      {abierto && <button type="button" className="menu-fondo" aria-label="Cerrar menú" onClick={() => setAbierto(false)} />}
      <aside id="menu-lateral" className={`menu ${colegio.menu_claro ? 'claro' : 'oscuro'} ${abierto ? 'abierto' : ''}`}>
        <div className="menu-colegio">
          <Logo colegio={colegio} className="menu-logo" />
          <div>
            <b>{colegio.nombre}</b>
            {datos.anio && <span>Año escolar {datos.anio}</span>}
          </div>
          <button type="button" className="menu-cerrar boton-icono" aria-label="Cerrar menú" onClick={() => setAbierto(false)}>
            <X aria-hidden="true" />
          </button>
        </div>
        <nav className="menu-grupos" aria-label="Menú principal">
          {grupos.map(([titulo, items]) => (
            <div key={titulo} className="menu-grupo">
              <h2 className="menu-titulo">{titulo}</h2>
              <ul>
                {items.map((i) => (
                  <li key={i.a}>
                    <NavLink to={i.a} end={i.fin}
                             className={({ isActive }) => (i.activo ?? isActive) ? 'active' : ''}>
                      <i.icono size={20} aria-hidden="true" />
                      <span className="menu-texto">{i.texto}</span>
                      {i.vivo && <span className="menu-vivo"><i aria-hidden="true" />En vivo</span>}
                      {i.contador > 0 && <span className="menu-contador" title={`${i.contador} ${i.titulo}`}>
                        {i.contador}<span className="solo-lectores"> {i.titulo}</span></span>}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <div className="menu-pie">
          <div className="menu-usuario">
            <span className="menu-iniciales" aria-hidden="true">{iniciales(`${yo.nombres} ${yo.apellidos}`)}</span>
            <span className="menu-quien"><b>{yo.nombres} {yo.apellidos}</b><span>{yo.rol}</span></span>
            <NavLink to="/panel/clave" className="boton-icono menu-accion" aria-label="Cambiar mi clave" title="Cambiar mi clave">
              <KeyRound size={18} aria-hidden="true" />
            </NavLink>
            <button type="button" className="boton-icono menu-accion" aria-label="Cerrar sesión" title="Cerrar sesión" onClick={salir}>
              <LogOut size={18} aria-hidden="true" />
            </button>
          </div>
          <Apariencia />
          <small className="menu-tikray">Plataforma de Tikray Labs</small>
        </div>
      </aside>
    </>
  )
}
