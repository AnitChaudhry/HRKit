import Navbar from './components/Navbar';
import Hero from './components/Hero';
import StartSection from './components/StartSection';
import ModulesShowcase from './components/ModulesShowcase';
import FeaturesChess from './components/FeaturesChess';
import FeaturesGrid from './components/FeaturesGrid';
import Stats from './components/Stats';
import Testimonials from './components/Testimonials';
import CtaFooter from './components/CtaFooter';
import StarField from './components/StarField';

export default function App() {
  return (
    <div className="bg-black min-h-screen">
      <StarField />
      <div className="relative z-10">
        <Navbar />
        <Hero />
        <div className="bg-black/60">
          <StartSection />
          <ModulesShowcase />
          <FeaturesChess />
          <FeaturesGrid />
          <Stats />
          <Testimonials />
          <CtaFooter />
        </div>
      </div>
    </div>
  );
}
